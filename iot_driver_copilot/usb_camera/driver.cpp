#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
#include <thread>
#include <chrono>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <json/json.h> // Requires jsoncpp library
#include "mqtt/async_client.h" // Requires Eclipse Paho MQTT C++ library

// MQTT Topics
constexpr const char* TOPIC_VIDEO_STREAM = "device/telemetry/video_stream";
constexpr const char* TOPIC_AUDIO_STREAM = "device/telemetry/audio_stream";
constexpr const char* TOPIC_CMD_START_CAPTURE = "device/commands/start_capture";
constexpr const char* TOPIC_CMD_STOP_CAPTURE = "device/commands/stop_capture";
constexpr const char* TOPIC_CMD_ADJUST_RESOLUTION = "device/commands/adjust_resolution";
constexpr const char* TOPIC_CMD_ADJUST_BRIGHTNESS = "device/commands/adjust_brightness";
constexpr const char* TOPIC_CMD_ADJUST_CONTRAST = "device/commands/adjust_contrast";

// QoS
constexpr int QOS_1 = 1;

// Utility for environment variables
inline std::string getenv_or_throw(const char* key) {
    const char* val = std::getenv(key);
    if (!val)
        throw std::runtime_error(std::string("Missing required environment variable: ") + key);
    return std::string(val);
}

// Camera Driver Class
class USBCameraMQTTDriver {
public:
    USBCameraMQTTDriver()
        : brokerAddress(getenv_or_throw("MQTT_BROKER_ADDRESS")),
          clientId("usb_camera_deviceShifu_" + std::to_string(std::rand())),
          cli(brokerAddress, clientId),
          connected(false)
    {
        connect();
    }

    ~USBCameraMQTTDriver() {
        disconnect();
    }

    // -- DeviceShifu API methods for user
    // (Call these from user code, not for internal driver operation)

    // 1. Subscribe to video stream
    void subscribeVideoStream(std::function<void(const std::string&)> handler) {
        subscribeTopic(TOPIC_VIDEO_STREAM, QOS_1, handler);
    }

    // 2. Subscribe to audio stream
    void subscribeAudioStream(std::function<void(const std::string&)> handler) {
        subscribeTopic(TOPIC_AUDIO_STREAM, QOS_1, handler);
    }

    // 3. Start capture
    void startCapture(const Json::Value& params = Json::Value()) {
        publishCommand(TOPIC_CMD_START_CAPTURE, params);
    }

    // 4. Stop capture
    void stopCapture() {
        publishCommand(TOPIC_CMD_STOP_CAPTURE, Json::Value());
    }

    // 5. Adjust resolution
    void adjustResolution(int width, int height) {
        Json::Value payload;
        payload["width"] = width;
        payload["height"] = height;
        publishCommand(TOPIC_CMD_ADJUST_RESOLUTION, payload);
    }

    // 6. Adjust brightness
    void adjustBrightness(int brightness) {
        Json::Value payload;
        payload["brightness"] = brightness;
        publishCommand(TOPIC_CMD_ADJUST_BRIGHTNESS, payload);
    }

    // 7. Adjust contrast
    void adjustContrast(int contrast) {
        Json::Value payload;
        payload["contrast"] = contrast;
        publishCommand(TOPIC_CMD_ADJUST_CONTRAST, payload);
    }

    // -- Internal driver (Shifu) logic: Use these to actually interact with MQTT (not for user API)

    // Subscribe to a topic; used internally by DeviceShifu to manage subscriptions.
    void subscribeTopic(const std::string& topic, int qos, std::function<void(const std::string&)> userHandler) {
        std::unique_lock<std::mutex> lock(sub_mutex);
        handlers[topic] = userHandler;
        cli.set_callback([this](mqtt::const_message_ptr msg) {
            std::string topic = msg->get_topic();
            std::string payload = msg->to_string();
            std::lock_guard<std::mutex> lock(this->sub_mutex);
            auto it = this->handlers.find(topic);
            if (it != this->handlers.end() && it->second) {
                it->second(payload);
            }
        });

        if (connected) {
            cli.subscribe(topic, qos)->wait();
        } else {
            pending_subs.emplace_back(topic, qos);
        }
    }

    // Publish a command (used internally to forward user commands over MQTT)
    void publishCommand(const std::string& topic, const Json::Value& payload) {
        Json::StreamWriterBuilder writer;
        std::string payloadStr = Json::writeString(writer, payload);
        auto msg = mqtt::make_message(topic, payloadStr, QOS_1, false);
        cli.publish(msg)->wait();
    }

private:
    std::string brokerAddress;
    std::string clientId;
    mqtt::async_client cli;
    std::atomic<bool> connected;

    std::mutex sub_mutex;
    std::map<std::string, std::function<void(const std::string&)>> handlers;
    std::vector<std::pair<std::string, int>> pending_subs;

    void connect() {
        mqtt::connect_options connOpts;
        connOpts.set_automatic_reconnect(true);
        connOpts.set_clean_session(true);

        cli.set_connected_handler([this](const std::string&) {
            connected = true;
            std::lock_guard<std::mutex> lock(this->sub_mutex);
            for (const auto& sub : pending_subs) {
                cli.subscribe(sub.first, sub.second)->wait();
            }
            pending_subs.clear();
        });

        cli.set_connection_lost_handler([this](const std::string&) {
            connected = false;
        });

        cli.connect(connOpts)->wait();
    }

    void disconnect() {
        try {
            cli.disconnect()->wait();
        } catch (...) {}
    }
};

// Example usage (main function is optional, remove if not needed)
#ifdef DRIVER_MAIN
int main() {
    try {
        USBCameraMQTTDriver driver;

        // Example: subscribe to video stream
        driver.subscribeVideoStream([](const std::string& payload) {
            std::cout << "Video stream payload: " << payload << std::endl;
        });

        // Example: start capture
        driver.startCapture();

        // Run for 60 seconds, then stop
        std::this_thread::sleep_for(std::chrono::seconds(60));
        driver.stopCapture();

    } catch (const std::exception& ex) {
        std::cerr << "Driver error: " << ex.what() << std::endl;
        return 1;
    }
    return 0;
}
#endif