#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <map>
#include <thread>
#include <cstdlib>
#include <csignal>
#include <chrono>
#include <mutex>
#include <atomic>
#include <vector>
#include <cstring>
#include <nlohmann/json.hpp>
#include <yaml-cpp/yaml.h>
#include <httplib.h>
#include <curl/curl.h>

// For Kubernetes in-cluster API
#include <openssl/ssl.h>
#include <openssl/x509.h>

// ----------------------
// Utility and Structures
// ----------------------

struct ProtocolSettings {
    std::map<std::string, std::string> properties;
};

struct APIInstructionSet {
    std::map<std::string, ProtocolSettings> apiMap;
};

static std::mutex status_mtx;
static std::atomic<bool> running(true);

// Read File Utility
std::string read_file(const std::string& filepath) {
    std::ifstream file(filepath);
    if (!file) return "";
    std::ostringstream ss;
    ss << file.rdbuf();
    return ss.str();
}

// Environment Variable Utility
std::string get_env(const std::string& var, const std::string& default_val = "") {
    const char* val = std::getenv(var.c_str());
    return val ? std::string(val) : default_val;
}

// ------------------------------
// Kubernetes In-cluster API Utils
// ------------------------------

struct KubeAPIConfig {
    std::string token;
    std::string ca_cert;
    std::string host;
};

KubeAPIConfig load_kube_config() {
    KubeAPIConfig cfg;
    cfg.token = read_file("/var/run/secrets/kubernetes.io/serviceaccount/token");
    cfg.ca_cert = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt";
    cfg.host = get_env("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc");
    return cfg;
}

std::string kube_api_url(const std::string& ns, const std::string& name) {
    return "/apis/shifu.edgenesis.io/v1alpha1/namespaces/" + ns + "/edgedevices/" + name;
}

CURL* curl_easy_init_with_cert(const KubeAPIConfig& cfg) {
    CURL* curl = curl_easy_init();
    if (!curl) return nullptr;
    std::string url = "https://" + cfg.host;
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_CAINFO, cfg.ca_cert.c_str());
    struct curl_slist* chunk = NULL;
    std::string auth = "Authorization: Bearer " + cfg.token;
    chunk = curl_slist_append(chunk, auth.c_str());
    chunk = curl_slist_append(chunk, "Content-Type: application/merge-patch+json");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, chunk);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);
    return curl;
}

size_t curl_write_cb(void* ptr, size_t size, size_t nmemb, void* userdata) {
    std::string* out = static_cast<std::string*>(userdata);
    out->append((char*)ptr, size * nmemb);
    return size * nmemb;
}

// Patch EdgeDevice Status
bool patch_edgedevice_phase(const std::string& ns, const std::string& name, const std::string& phase) {
    KubeAPIConfig cfg = load_kube_config();
    std::string url = "https://" + cfg.host + kube_api_url(ns, name) + "/status";
    std::string patch = R"({"status":{"edgeDevicePhase":")" + phase + R"("}})";

    CURL* curl = curl_easy_init();
    if (!curl) return false;
    struct curl_slist* chunk = NULL;
    chunk = curl_slist_append(chunk, ("Authorization: Bearer " + cfg.token).c_str());
    chunk = curl_slist_append(chunk, "Content-Type: application/merge-patch+json");
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, chunk);
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PATCH");
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, patch.c_str());
    curl_easy_setopt(curl, CURLOPT_CAINFO, cfg.ca_cert.c_str());
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);

    std::string response;
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);

    CURLcode res = curl_easy_perform(curl);
    long status_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status_code);
    curl_easy_cleanup(curl);
    if (res != CURLE_OK || (status_code < 200 || status_code >= 300)) return false;
    return true;
}

// Get EdgeDevice Spec
bool get_edgedevice_spec(const std::string& ns, const std::string& name, nlohmann::json& spec) {
    KubeAPIConfig cfg = load_kube_config();
    std::string url = "https://" + cfg.host + kube_api_url(ns, name);
    CURL* curl = curl_easy_init();
    if (!curl) return false;
    struct curl_slist* chunk = NULL;
    chunk = curl_slist_append(chunk, ("Authorization: Bearer " + cfg.token).c_str());
    chunk = curl_slist_append(chunk, "Accept: application/json");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, chunk);
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_CAINFO, cfg.ca_cert.c_str());
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);

    std::string response;
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    if (res != CURLE_OK) return false;

    try {
        auto json = nlohmann::json::parse(response);
        if (json.contains("spec")) {
            spec = json["spec"];
            return true;
        }
    } catch (...) {
        return false;
    }
    return false;
}

// ---------------------
// YAML ConfigMap Loader
// ---------------------

APIInstructionSet load_api_instructions(const std::string& filepath) {
    APIInstructionSet set;
    auto node = YAML::LoadFile(filepath);
    for (const auto& it : node) {
        std::string api = it.first.as<std::string>();
        ProtocolSettings prop;
        auto propList = it.second["protocolPropertyList"];
        if (propList) {
            for (const auto& p : propList) {
                prop.properties[p.first.as<std::string>()] = p.second.as<std::string>();
            }
        }
        set.apiMap[api] = prop;
    }
    return set;
}

// ---------------------------------------
// ROS2 Bridge WebSocket Communication Stub
// ---------------------------------------

class Ros2BridgeClient {
    std::string ws_url;
    std::atomic<bool> connected_;
    std::mutex mtx;
public:
    Ros2BridgeClient(const std::string& address)
        : ws_url(address), connected_(false) {}

    bool connect() {
        // Here, stubbed as always successful.
        std::lock_guard<std::mutex> lk(mtx);
        connected_ = true;
        return connected_;
    }

    bool is_connected() {
        std::lock_guard<std::mutex> lk(mtx);
        return connected_;
    }

    bool send_movement_command(const std::string& direction) {
        // Simulate sending a movement command via websocket/ros2 bridge.
        // In real code, implement actual websocket send.
        if (!is_connected()) return false;
        // Simulate a small delay
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        return direction == "forward" || direction == "backward" ||
               direction == "left" || direction == "right" || direction == "stop";
    }
};

// ---------------------
// HTTP Server & Routing
// ---------------------

std::string get_status_string(bool ok) {
    return ok ? "Running" : "Failed";
}

void handle_move(const httplib::Request& req, httplib::Response& res, Ros2BridgeClient& client) {
    nlohmann::json resp;
    try {
        auto payload = nlohmann::json::parse(req.body);
        std::string direction = payload.value("direction", "");
        if (direction.empty()) {
            res.status = 400;
            resp["status"] = "error";
            resp["message"] = "Missing 'direction' field";
            res.set_content(resp.dump(), "application/json");
            return;
        }
        bool ok = client.send_movement_command(direction);
        if (ok) {
            res.status = 200;
            resp["status"] = "ok";
            resp["direction"] = direction;
            resp["message"] = "Movement command sent";
        } else {
            res.status = 500;
            resp["status"] = "fail";
            resp["message"] = "Failed to send command";
        }
        res.set_content(resp.dump(), "application/json");
    } catch (...) {
        res.status = 400;
        resp["status"] = "error";
        resp["message"] = "Invalid JSON payload";
        res.set_content(resp.dump(), "application/json");
    }
}

// ---------------------
// Main
// ---------------------

std::atomic<std::string> phase("Pending");

void update_phase_thread(Ros2BridgeClient* bridge,
                        const std::string ns,
                        const std::string name) {
    while (running) {
        std::string new_phase = "Unknown";
        if (bridge->is_connected()) new_phase = "Running";
        else new_phase = "Pending";
        {
            std::lock_guard<std::mutex> lk(status_mtx);
            if (phase.load() != new_phase) {
                if (patch_edgedevice_phase(ns, name, new_phase)) phase.store(new_phase);
            }
        }
        std::this_thread::sleep_for(std::chrono::seconds(5));
    }
}

void sigint_handler(int) {
    running = false;
}

int main() {
    signal(SIGINT, sigint_handler);
    // Environment Variables
    std::string edgedevice_name = get_env("EDGEDEVICE_NAME");
    std::string edgedevice_namespace = get_env("EDGEDEVICE_NAMESPACE");
    std::string server_host = get_env("SERVER_HOST", "0.0.0.0");
    int server_port = std::stoi(get_env("SERVER_PORT", "8080"));

    if (edgedevice_name.empty() || edgedevice_namespace.empty()) {
        std::cerr << "EDGEDEVICE_NAME and EDGEDEVICE_NAMESPACE env required" << std::endl;
        return 1;
    }

    // Load instructions
    std::string instructions_path = "/etc/edgedevice/config/instructions";
    APIInstructionSet instruction_set = load_api_instructions(instructions_path);

    // Get EdgeDevice Spec (address)
    nlohmann::json edgedevice_spec;
    std::string device_address;
    if (get_edgedevice_spec(edgedevice_namespace, edgedevice_name, edgedevice_spec)) {
        if (edgedevice_spec.contains("address")) {
            device_address = edgedevice_spec["address"].get<std::string>();
        }
    }
    if (device_address.empty()) {
        std::cerr << "No device address found in EdgeDevice spec" << std::endl;
        patch_edgedevice_phase(edgedevice_namespace, edgedevice_name, "Unknown");
        return 1;
    }

    // ROS2 Bridge Client setup
    Ros2BridgeClient ros2_client(device_address);
    bool connected = ros2_client.connect();
    patch_edgedevice_phase(edgedevice_namespace, edgedevice_name, connected ? "Running" : "Failed");
    phase.store(connected ? "Running" : "Failed");

    // Start status update thread
    std::thread upd_thr(update_phase_thread, &ros2_client, edgedevice_namespace, edgedevice_name);

    // HTTP Server
    httplib::Server svr;

    svr.Post("/move", [&](const httplib::Request& req, httplib::Response& res) {
        handle_move(req, res, ros2_client);
    });

    // Healthz
    svr.Get("/healthz", [](const httplib::Request&, httplib::Response& res) {
        res.set_content("{\"status\":\"ok\"}", "application/json");
    });

    svr.listen(server_host.c_str(), server_port);

    running = false;
    upd_thr.join();
    patch_edgedevice_phase(edgedevice_namespace, edgedevice_name, "Pending");
    return 0;
}