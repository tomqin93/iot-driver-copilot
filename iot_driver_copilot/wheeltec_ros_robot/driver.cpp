#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <thread>
#include <chrono>
#include <vector>
#include <map>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <atomic>
#include <csignal>

// Networking includes
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>

// ROS
#include <ros/ros.h>
#include <std_msgs/Float32.h>
#include <sensor_msgs/Imu.h>
#include <nav_msgs/Odometry.h>
#include <sensor_msgs/LaserScan.h>
#include <sensor_msgs/Image.h>
#include <std_msgs/Bool.h>
#include <geometry_msgs/Twist.h>
#include <std_msgs/String.h>

// JSON utility
#include <jsoncpp/json/json.h>

#define BUFFER_SIZE 65536

// ================ Utility Functions ================

inline std::string getenv_default(const char* key, const char* dflt) {
    const char* v = std::getenv(key);
    if (v == nullptr) return std::string(dflt);
    return std::string(v);
}

inline int getenv_int(const char* key, int dflt) {
    const char* v = std::getenv(key);
    if (v == nullptr) return dflt;
    return std::atoi(v);
}

inline void http_send(int client_sock, const std::string& header, const std::string& body) {
    std::string resp = header + std::to_string(body.size()) + "\r\n\r\n" + body;
    send(client_sock, resp.c_str(), resp.size(), 0);
}

inline void http_send_json(int client_sock, const Json::Value& val) {
    Json::FastWriter fw;
    std::string out = fw.write(val);
    std::string header = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ";
    http_send(client_sock, header, out);
}

inline void http_error(int client_sock, int code, const std::string& msg) {
    std::ostringstream oss;
    oss << "HTTP/1.1 " << code << " ERROR\r\nContent-Type: text/plain\r\nContent-Length: " << msg.size() << "\r\n\r\n" << msg;
    send(client_sock, oss.str().c_str(), oss.str().size(), 0);
}

// ================ ROS Data Handlers ================

struct RobotStatus {
    float battery = 0.0f;
    nav_msgs::Odometry odom;
    sensor_msgs::Imu imu;
    sensor_msgs::LaserScan lidar;
    sensor_msgs::Image camera;
    std::mutex mtx;
    bool odom_ready = false, imu_ready = false, lidar_ready = false, camera_ready = false, battery_ready = false;
};

RobotStatus g_status;

void battery_cb(const std_msgs::Float32::ConstPtr& msg) {
    std::lock_guard<std::mutex> lk(g_status.mtx);
    g_status.battery = msg->data;
    g_status.battery_ready = true;
}
void odom_cb(const nav_msgs::Odometry::ConstPtr& msg) {
    std::lock_guard<std::mutex> lk(g_status.mtx);
    g_status.odom = *msg;
    g_status.odom_ready = true;
}
void imu_cb(const sensor_msgs::Imu::ConstPtr& msg) {
    std::lock_guard<std::mutex> lk(g_status.mtx);
    g_status.imu = *msg;
    g_status.imu_ready = true;
}
void lidar_cb(const sensor_msgs::LaserScan::ConstPtr& msg) {
    std::lock_guard<std::mutex> lk(g_status.mtx);
    g_status.lidar = *msg;
    g_status.lidar_ready = true;
}
void camera_cb(const sensor_msgs::Image::ConstPtr& msg) {
    std::lock_guard<std::mutex> lk(g_status.mtx);
    g_status.camera = *msg;
    g_status.camera_ready = true;
}

// ================ HTTP Server ================

class HttpServer {
public:
    HttpServer(const std::string& host, int port)
        : m_host(host), m_port(port), m_running(false) {}

    void start(std::function<void(int)> client_handler) {
        m_running = true;
        m_thread = std::thread([this, client_handler]() {
            run(client_handler);
        });
    }

    void stop() {
        m_running = false;
        if (m_sock != -1) close(m_sock);
        if (m_thread.joinable()) m_thread.join();
    }

    ~HttpServer() { stop(); }

private:
    std::string m_host;
    int m_port;
    std::atomic<bool> m_running;
    std::thread m_thread;
    int m_sock = -1;

    void run(std::function<void(int)> client_handler) {
        m_sock = socket(AF_INET, SOCK_STREAM, 0);
        int opt = 1;
        setsockopt(m_sock, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

        sockaddr_in addr;
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(m_port);
        if (bind(m_sock, (sockaddr*)&addr, sizeof(addr)) < 0) {
            perror("bind failed");
            exit(1);
        }
        if (listen(m_sock, 16) < 0) {
            perror("listen failed");
            exit(1);
        }
        while (m_running) {
            sockaddr_in c_addr;
            socklen_t clen = sizeof(c_addr);
            int client = accept(m_sock, (sockaddr*)&c_addr, &clen);
            if (client < 0) continue;
            std::thread([client, client_handler]() {
                client_handler(client);
                close(client);
            }).detach();
        }
    }
};

// ================ HTTP Request Router ================

void handle_status(int client_sock) {
    Json::Value root;
    {
        std::lock_guard<std::mutex> lk(g_status.mtx);

        // Battery
        root["battery"] = g_status.battery_ready ? g_status.battery : Json::Value();

        // Odometry
        if (g_status.odom_ready) {
            const auto& o = g_status.odom;
            root["odometry"]["x"] = o.pose.pose.position.x;
            root["odometry"]["y"] = o.pose.pose.position.y;
            root["odometry"]["z"] = o.pose.pose.position.z;
            root["odometry"]["orientation"]["x"] = o.pose.pose.orientation.x;
            root["odometry"]["orientation"]["y"] = o.pose.pose.orientation.y;
            root["odometry"]["orientation"]["z"] = o.pose.pose.orientation.z;
            root["odometry"]["orientation"]["w"] = o.pose.pose.orientation.w;
            root["odometry"]["linear"]["x"] = o.twist.twist.linear.x;
            root["odometry"]["linear"]["y"] = o.twist.twist.linear.y;
            root["odometry"]["linear"]["z"] = o.twist.twist.linear.z;
            root["odometry"]["angular"]["x"] = o.twist.twist.angular.x;
            root["odometry"]["angular"]["y"] = o.twist.twist.angular.y;
            root["odometry"]["angular"]["z"] = o.twist.twist.angular.z;
        }
        // IMU
        if (g_status.imu_ready) {
            const auto& i = g_status.imu;
            root["imu"]["orientation"]["x"] = i.orientation.x;
            root["imu"]["orientation"]["y"] = i.orientation.y;
            root["imu"]["orientation"]["z"] = i.orientation.z;
            root["imu"]["orientation"]["w"] = i.orientation.w;
            root["imu"]["angular_velocity"]["x"] = i.angular_velocity.x;
            root["imu"]["angular_velocity"]["y"] = i.angular_velocity.y;
            root["imu"]["angular_velocity"]["z"] = i.angular_velocity.z;
            root["imu"]["linear_acceleration"]["x"] = i.linear_acceleration.x;
            root["imu"]["linear_acceleration"]["y"] = i.linear_acceleration.y;
            root["imu"]["linear_acceleration"]["z"] = i.linear_acceleration.z;
        }
        // Lidar
        if (g_status.lidar_ready) {
            const auto& l = g_status.lidar;
            for (float r : l.ranges) root["lidar"]["ranges"].append(r);
            root["lidar"]["angle_min"] = l.angle_min;
            root["lidar"]["angle_max"] = l.angle_max;
            root["lidar"]["angle_increment"] = l.angle_increment;
            root["lidar"]["time_increment"] = l.time_increment;
            root["lidar"]["scan_time"] = l.scan_time;
            root["lidar"]["range_min"] = l.range_min;
            root["lidar"]["range_max"] = l.range_max;
        }
        // Camera
        if (g_status.camera_ready) {
            const auto& c = g_status.camera;
            root["camera"]["width"] = c.width;
            root["camera"]["height"] = c.height;
            root["camera"]["encoding"] = c.encoding;
            root["camera"]["step"] = c.step;
            root["camera"]["data_len"] = (Json::UInt64)c.data.size();
            // For brevity, do not include raw image bytes in status response
        }
    }
    http_send_json(client_sock, root);
}

// Helper: Read all data for POST
std::string read_http_body(int client_sock, int content_length) {
    std::string body;
    body.reserve(content_length);
    int total = 0;
    while (total < content_length) {
        char buf[4096];
        int to_read = std::min(4096, content_length - total);
        int n = recv(client_sock, buf, to_read, 0);
        if (n <= 0) break;
        body.append(buf, n);
        total += n;
    }
    return body;
}

// Navigation command publisher (topic, type, etc. must match ROS system)
ros::Publisher g_nav_pub;
ros::Publisher g_move_pub;

// /nav POST: expects JSON body with fields: "points" (array of [x,y]), "algorithm" ("dijkstra" or "astar")
void handle_nav(int client_sock, const std::string& body) {
    Json::Value req;
    Json::Reader jr;
    if (!jr.parse(body, req)) {
        http_error(client_sock, 400, "Invalid JSON");
        return;
    }
    if (!req.isMember("points") || !req["points"].isArray()) {
        http_error(client_sock, 400, "Missing 'points' array");
        return;
    }
    std::string algorithm = req.get("algorithm", "dijkstra").asString();

    std_msgs::String msg;
    Json::FastWriter fw;
    msg.data = fw.write(req);
    g_nav_pub.publish(msg);

    Json::Value resp;
    resp["status"] = "ok";
    resp["algorithm"] = algorithm;
    http_send_json(client_sock, resp);
}

// /move POST: expects JSON body with "linear" (float), "angular" (float)
void handle_move(int client_sock, const std::string& body) {
    Json::Value req;
    Json::Reader jr;
    if (!jr.parse(body, req)) {
        http_error(client_sock, 400, "Invalid JSON");
        return;
    }
    if (!req.isMember("linear") || !req.isMember("angular")) {
        http_error(client_sock, 400, "Missing 'linear' or 'angular'");
        return;
    }
    double linear = req["linear"].asDouble();
    double angular = req["angular"].asDouble();

    geometry_msgs::Twist msg;
    msg.linear.x = linear;
    msg.angular.z = angular;
    g_move_pub.publish(msg);

    Json::Value resp;
    resp["status"] = "ok";
    resp["linear"] = linear;
    resp["angular"] = angular;
    http_send_json(client_sock, resp);
}

// Parse HTTP request and route
void http_router(int client_sock) {
    char buf[BUFFER_SIZE];
    int n = recv(client_sock, buf, sizeof(buf)-1, 0);
    if (n <= 0) return;
    buf[n] = 0;
    std::string req(buf, n);

    std::istringstream iss(req);
    std::string method, path, ver;
    iss >> method >> path >> ver;

    // Read headers
    std::map<std::string, std::string> headers;
    std::string line;
    int content_length = 0;
    while (std::getline(iss, line) && line != "\r") {
        if (line.empty() || line == "\n" || line == "\r\n") break;
        auto pos = line.find(':');
        if (pos != std::string::npos) {
            std::string key = line.substr(0, pos);
            std::string val = line.substr(pos+1);
            while (!val.empty() && (val[0] == ' ' || val[0] == '\t')) val = val.substr(1);
            val.erase(val.find_last_not_of("\r\n") + 1);
            headers[key] = val;
            if (key == "Content-Length") content_length = std::stoi(val);
        }
    }

    // Handle endpoints
    if (method == "GET" && path == "/status") {
        handle_status(client_sock);
    } else if (method == "POST" && path == "/nav") {
        std::string body = read_http_body(client_sock, content_length);
        handle_nav(client_sock, body);
    } else if (method == "POST" && path == "/move") {
        std::string body = read_http_body(client_sock, content_length);
        handle_move(client_sock, body);
    } else {
        http_error(client_sock, 404, "Not found");
    }
}

// ================ Main Entry ================

std::atomic<bool> running(true);

void signal_handler(int sig) {
    running = false;
}

int main(int argc, char** argv) {
    // Load config from environment
    std::string ROS_MASTER_URI = getenv_default("ROS_MASTER_URI", "http://localhost:11311");
    std::string ROS_HOSTNAME = getenv_default("ROS_HOSTNAME", "localhost");
    std::string HTTP_SERVER_HOST = getenv_default("HTTP_SERVER_HOST", "0.0.0.0");
    int HTTP_SERVER_PORT = getenv_int("HTTP_SERVER_PORT", 8080);

    // Set ROS env
    setenv("ROS_MASTER_URI", ROS_MASTER_URI.c_str(), 1);
    setenv("ROS_HOSTNAME", ROS_HOSTNAME.c_str(), 1);

    ros::init(argc, argv, "wheeltec_http_driver");
    ros::NodeHandle nh;

    // ROS Subscribers
    ros::Subscriber battery_sub = nh.subscribe("/battery", 1, battery_cb);
    ros::Subscriber odom_sub = nh.subscribe("/odom", 1, odom_cb);
    ros::Subscriber imu_sub = nh.subscribe("/imu", 1, imu_cb);
    ros::Subscriber lidar_sub = nh.subscribe("/scan", 1, lidar_cb);
    ros::Subscriber camera_sub = nh.subscribe("/camera/rgb/image_raw", 1, camera_cb);

    // ROS Publishers
    g_nav_pub = nh.advertise<std_msgs::String>("/nav_cmd", 1);
    g_move_pub = nh.advertise<geometry_msgs::Twist>("/cmd_vel", 1);

    // HTTP Server
    HttpServer server(HTTP_SERVER_HOST, HTTP_SERVER_PORT);
    server.start(http_router);

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    // Spin in ROS + keep HTTP server running
    while (ros::ok() && running) {
        ros::spinOnce();
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    server.stop();
    return 0;
}