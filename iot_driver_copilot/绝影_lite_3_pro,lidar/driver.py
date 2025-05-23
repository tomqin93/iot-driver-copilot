import os
import threading
import json
import time
from flask import Flask, request, Response, jsonify
import rospy
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped, PoseStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu, JointState, Image, PointCloud2
from std_msgs.msg import Header
from cv_bridge import CvBridge
import numpy as np

# Environment Variables
ROS_MASTER_URI = os.environ.get("ROS_MASTER_URI", "http://localhost:11311")
ROS_HOSTNAME = os.environ.get("ROS_HOSTNAME", "localhost")
HTTP_SERVER_HOST = os.environ.get("HTTP_SERVER_HOST", "0.0.0.0")
HTTP_SERVER_PORT = int(os.environ.get("HTTP_SERVER_PORT", "8000"))

os.environ["ROS_MASTER_URI"] = ROS_MASTER_URI
os.environ["ROS_HOSTNAME"] = ROS_HOSTNAME

app = Flask(__name__)

rospy_inited = False
data_lock = threading.Lock()
latest_data = {
    "leg_odom": None,
    "imu": None,
    "joint_states": None,
    "depth_image": None,
    "point_cloud": None,
}

bridge = CvBridge()

def init_ros():
    global rospy_inited
    if not rospy_inited:
        rospy.init_node("device_http_driver", anonymous=True, disable_signals=True)
        rospy_inited = True

def odom_callback(msg):
    with data_lock:
        latest_data["leg_odom"] = {
            "pose": {
                "position": {
                    "x": msg.pose.pose.position.x,
                    "y": msg.pose.pose.position.y,
                    "z": msg.pose.pose.position.z,
                },
                "orientation": {
                    "x": msg.pose.pose.orientation.x,
                    "y": msg.pose.pose.orientation.y,
                    "z": msg.pose.pose.orientation.z,
                    "w": msg.pose.pose.orientation.w,
                },
            },
            "twist": {
                "linear": {
                    "x": msg.twist.twist.linear.x,
                    "y": msg.twist.twist.linear.y,
                    "z": msg.twist.twist.linear.z,
                },
                "angular": {
                    "x": msg.twist.twist.angular.x,
                    "y": msg.twist.twist.angular.y,
                    "z": msg.twist.twist.angular.z,
                },
            },
            "header": {
                "stamp": msg.header.stamp.to_sec(),
                "frame_id": msg.header.frame_id,
            }
        }

def imu_callback(msg):
    with data_lock:
        latest_data["imu"] = {
            "orientation": {
                "x": msg.orientation.x,
                "y": msg.orientation.y,
                "z": msg.orientation.z,
                "w": msg.orientation.w,
            },
            "angular_velocity": {
                "x": msg.angular_velocity.x,
                "y": msg.angular_velocity.y,
                "z": msg.angular_velocity.z,
            },
            "linear_acceleration": {
                "x": msg.linear_acceleration.x,
                "y": msg.linear_acceleration.y,
                "z": msg.linear_acceleration.z,
            },
            "header": {
                "stamp": msg.header.stamp.to_sec(),
                "frame_id": msg.header.frame_id,
            }
        }

def joint_states_callback(msg):
    with data_lock:
        latest_data["joint_states"] = {
            "name": list(msg.name),
            "position": list(msg.position),
            "velocity": list(msg.velocity),
            "effort": list(msg.effort),
            "header": {
                "stamp": msg.header.stamp.to_sec(),
                "frame_id": msg.header.frame_id,
            }
        }

def depth_image_callback(msg):
    try:
        cv_img = bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        # Convert to PNG for browser
        import cv2
        import io
        ret, buf = cv2.imencode('.png', cv_img)
        if ret:
            with data_lock:
                latest_data["depth_image"] = buf.tobytes()
    except Exception:
        pass

def point_cloud_callback(msg):
    # Return raw data as bytes; for point cloud, browser will download it
    with data_lock:
        latest_data["point_cloud"] = {
            "data": msg.data,
            "fields": [f.name for f in msg.fields],
            "height": msg.height,
            "width": msg.width,
            "is_dense": msg.is_dense,
            "header": {
                "stamp": msg.header.stamp.to_sec(),
                "frame_id": msg.header.frame_id,
            }
        }

def ros_subscribers_thread():
    init_ros()
    rospy.Subscriber("/leg_odom", Odometry, odom_callback)
    rospy.Subscriber("/imu/data", Imu, imu_callback)
    rospy.Subscriber("/joint_states", JointState, joint_states_callback)
    rospy.Subscriber("/camera/depth/image_raw", Image, depth_image_callback)
    rospy.Subscriber("/camera/depth/points", PointCloud2, point_cloud_callback)
    rospy.spin()

ros_thread = threading.Thread(target=ros_subscribers_thread, daemon=True)
ros_thread.start()

@app.route("/sdata", methods=["GET"])
def sdata():
    # Returns latest sensor readings
    with data_lock:
        result = {
            "leg_odom": latest_data["leg_odom"],
            "imu": latest_data["imu"],
            "joint_states": latest_data["joint_states"]
        }
    return jsonify(result)

@app.route("/sdata/depth_image", methods=["GET"])
def depth_image():
    with data_lock:
        img_bytes = latest_data.get("depth_image")
        if img_bytes:
            return Response(img_bytes, mimetype="image/png")
        else:
            return Response("No image", status=404)

@app.route("/sdata/point_cloud", methods=["GET"])
def point_cloud():
    with data_lock:
        pc = latest_data.get("point_cloud")
        if pc:
            return Response(pc["data"], mimetype="application/octet-stream",
                            headers={
                                "Content-Disposition": "attachment; filename=point_cloud.bin"
                            })
        else:
            return Response("No point cloud", status=404)

@app.route("/move", methods=["POST"])
def move():
    data = request.json
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    linear = data.get("linear", {})
    angular = data.get("angular", {})
    try:
        init_ros()
        pub = rospy.Publisher("/cmd_vel", Twist, queue_size=1)
        twist = Twist()
        twist.linear.x = float(linear.get("x", 0))
        twist.linear.y = float(linear.get("y", 0))
        twist.linear.z = float(linear.get("z", 0))
        twist.angular.x = float(angular.get("x", 0))
        twist.angular.y = float(angular.get("y", 0))
        twist.angular.z = float(angular.get("z", 0))
        # Publish command for a short duration
        for _ in range(5):
            pub.publish(twist)
            rospy.sleep(0.05)
        return jsonify({"status": "OK"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/goal", methods=["POST"])
def goal():
    data = request.json
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    x = data.get("x")
    y = data.get("y")
    theta = data.get("theta", 0)
    is_multi_goal = bool(data.get("multi_goal", False))
    try:
        init_ros()
        if is_multi_goal:
            # For multi-goal, assume a topic or action (example: /multi_goal)
            pub = rospy.Publisher("/multi_goal", PoseStamped, queue_size=1)
            pose = PoseStamped()
            pose.header = Header(stamp=rospy.Time.now(), frame_id="map")
            pose.pose.position.x = float(x)
            pose.pose.position.y = float(y)
            pose.pose.position.z = 0
            import tf
            quat = tf.transformations.quaternion_from_euler(0, 0, float(theta))
            pose.pose.orientation.x = quat[0]
            pose.pose.orientation.y = quat[1]
            pose.pose.orientation.z = quat[2]
            pose.pose.orientation.w = quat[3]
            pub.publish(pose)
        else:
            pub = rospy.Publisher("/move_base_simple/goal", PoseStamped, queue_size=1)
            pose = PoseStamped()
            pose.header = Header(stamp=rospy.Time.now(), frame_id="map")
            pose.pose.position.x = float(x)
            pose.pose.position.y = float(y)
            pose.pose.position.z = 0
            import tf
            quat = tf.transformations.quaternion_from_euler(0, 0, float(theta))
            pose.pose.orientation.x = quat[0]
            pose.pose.orientation.y = quat[1]
            pose.pose.orientation.z = quat[2]
            pose.pose.orientation.w = quat[3]
            pub.publish(pose)
        return jsonify({"status": "OK"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/pose", methods=["POST"])
def pose():
    data = request.json
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    x = data.get("x")
    y = data.get("y")
    theta = data.get("theta", 0)
    try:
        init_ros()
        pub = rospy.Publisher("/initialpose", PoseWithCovarianceStamped, queue_size=1)
        pose = PoseWithCovarianceStamped()
        pose.header = Header(stamp=rospy.Time.now(), frame_id="map")
        pose.pose.pose.position.x = float(x)
        pose.pose.pose.position.y = float(y)
        pose.pose.pose.position.z = 0
        import tf
        quat = tf.transformations.quaternion_from_euler(0, 0, float(theta))
        pose.pose.pose.orientation.x = quat[0]
        pose.pose.pose.orientation.y = quat[1]
        pose.pose.pose.orientation.z = quat[2]
        pose.pose.pose.orientation.w = quat[3]
        # Set covariance to a default
        pose.pose.covariance = [0.25, 0, 0, 0, 0, 0,
                                0, 0.25, 0, 0, 0, 0,
                                0, 0, 0.25, 0, 0, 0,
                                0, 0, 0, 0.06853891945200942, 0, 0,
                                0, 0, 0, 0, 0.06853891945200942, 0,
                                0, 0, 0, 0, 0, 0.06853891945200942]
        for _ in range(3):
            pub.publish(pose)
            rospy.sleep(0.05)
        return jsonify({"status": "OK"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host=HTTP_SERVER_HOST, port=HTTP_SERVER_PORT)