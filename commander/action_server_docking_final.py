# Import
import rclpy
import time
import cv2
import cv2.aruco as aruco
import numpy as np

# From import
from rclpy.action import ActionServer
from docking_action_server.action import Docking
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist
from geometry_msgs.msg import Vector3

# Tracking variables
ownMarkerID = 1
arucoIDSearcher = 0
turnSpeed = 0.5
driveSpeed = 0

# Search for aruco marker variables
directionLookLeft = False
searchPeriod = 6
newTime = True
time_begin = time.time()
startSearch = True
targetDockingPos = [0, 0, 0.10] # given in meters
targetDockingAng = [0, 0, 0] # Given in degreess
completedDocking = False
maxSpeedZ = 0.07
maxSpeedX = 0.07
maxTurnSpeed = 0.10

# PID variables
integral, derivative, last_error = 0, 0, 0


class DockingActionServer(Node):

    global arucoIDSearcher, ownMarkerID

    def __init__(self):
        super().__init__('docking_action_server')
        self._action_server = ActionServer(
            self,
            Docking,
            'docking',
            self.execute_callback)
        self.startDocking = False
        self.arucoMarkerID = 0
        self.dockSucced = False

    def execute_callback(self, goal_handle):
        self.get_logger().info('Executing docking...')
        feedback_msg = Docking.Feedback()
        result = Docking.Result()

        if goal_handle.request.start_docking and goal_handle.request.feeder_id == ownMarkerID:
            self.dockSucced = False
            self.startDocking = True
            self.arucoMarkerID = goal_handle.request.carrier_id
            print("feeder_id: ", goal_handle.request.feeder_id)
            print('Starting to dock. Looking for carrier with an ID off: ' + str(arucoIDSearcher) + ".")
            feedback_msg.is_docking = True
            goal_handle.publish_feedback(feedback_msg)
            print("Caling Function")
            # Start camera
            cap = cv2.VideoCapture(0)

            # Load camera parameters
            mtx, dist = load_coefficients("/home/jetson/dev_ws/src/docking_action_server/commander/cali.yml")

            # Start motor publisher to contorl robot
            minimal_publisher = MinimalPublisher()
            
            while True:
                __, img = cap.read()

                foundArucos = findArucosMakers(img)
                foundArucosMarkers = len(foundArucos[0])

                if foundArucosMarkers > 0:
                    aruco.drawDetectedMarkers(img, foundArucos[0], foundArucos[1])
                    counter = 0
                    rvecs, tvecs, _ = aruco.estimatePoseSingleMarkers(foundArucos[0], 0.048, mtx, dist) # Aruco markers length are given in meters

                    hasSeenAruco = False
                    for bbox, id in zip(foundArucos[0], foundArucos[1]):
                        aruco.drawAxis(img, mtx, dist, rvecs[counter], tvecs[counter], 0.1)
                        counter += 1
                        
                        if id == self.arucoMarkerID:
                            controlDocking(minimal_publisher, rvecs, tvecs, self)
                            hasSeenAruco = True
                        elif id is not self.arucoMarkerID and not hasSeenAruco:
                            searchForAruco(minimal_publisher)
                else:
                    print("No Aruco markers found")
                    searchForAruco(minimal_publisher)

                if self.dockSucced:
                    goal_handle.succeed()

                    result = Docking.Result()
                    self.get_logger().info('Goal succeded...')

                    result.docked = True
                    return result

        elif not goal_handle.request.start_docking:
            self.startDocking = False
            feedback_msg.is_docking = False
            self.arucoMarkerID = 0
            print("You requested me to not dock.")

        #result.docked = True

        return result


class MinimalPublisher(Node):

    """ Publishes the angular and linear velocity to cmd_vel to control the robot. """

    def __init__(self):
        super().__init__('cmd_vel_publisher')
        self.publisher_ = self.create_publisher(Twist, 'cmd_vel', 10)
        timer_period = 0.01  # seconds
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.linearVec = (0.0, 0.0, 0.0)
        self.angularVec = (0.0, 0.0, 0.0)

    def timer_callback(self):
        msg = Twist()

        msg.linear.x = self.linearVec[0]
        msg.linear.y = self.linearVec[1]
        msg.linear.z = self.linearVec[2]
        msg.angular.x = self.angularVec[0]
        msg.angular.y = self.angularVec[1]
        msg.angular.z = self.angularVec[2]

        self.publisher_.publish(msg)


def findArucosMakers(img, makerSize=6, totalMarkers=250, draw=False):

    """ Finds aruco markers from a given key (markersize and totalmarkers). """

    imgGray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # We use the key 6x6_250 for the Aruco markers type
    key = getattr(aruco, f'DICT_{makerSize}X{makerSize}_{totalMarkers}')
    arucoDict = aruco.Dictionary_get(key)
    arucoParam = aruco.DetectorParameters_create()
    bbox, ids, __ = aruco.detectMarkers(imgGray, arucoDict, parameters=arucoParam)

    if draw:
        aruco.drawDetectedMarkers(img, bbox)

    return[bbox, ids]


def load_coefficients(path):
    
    """ Loads camera matrix and distortion coefficients. """

    cv_file = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)

    camera_matrix = cv_file.getNode("K").mat()
    dist_matrix = cv_file.getNode("D").mat()

    cv_file.release()

    return camera_matrix, dist_matrix


def searchForAruco(minimal_publisher):

    """ Makes the robot turn left and right to look for any aruco markers. """

    global newTime, directionLookLeft, time_begin, startSearch, searchPeriod

    if newTime:
        time_begin = time.time()
        newTime = False
    elif startSearch:
        searchPeriod = 3
    elif not startSearch:
        searchPeriod = 6

    if time.time() - time_begin > searchPeriod:
        # Reset clock
        newTime = True
        startSearch = False
        directionLookLeft = np.invert(directionLookLeft)
    else:
        if directionLookLeft:
            turnLeft(minimal_publisher)
        else:
            turnRight(minimal_publisher)


def turnRight(minimal_publisher):
    minimal_publisher.angularVec = (0.0, 0.0, -turnSpeed)
    minimal_publisher.linearVec = (0.0, 0.0, 0.0)
    rclpy.spin_once(minimal_publisher)
    #print("Turning right with: " + str(-turnSpeed) + "rad/s.")


def turnLeft(minimal_publisher):
    minimal_publisher.angularVec = (0.0, 0.0, turnSpeed)
    minimal_publisher.linearVec = (0.0, 0.0, 0.0)
    rclpy.spin_once(minimal_publisher)
    #print("Turning left with: " + str(turnSpeed) + "rad/s.")


# PID function
def PID(error, Kp, Ki, Kd):
    global integral, derivative, last_error
    integral = integral + error
    derivative = error - last_error
    last_error = error
    return Kp * error + Ki * integral + Kd * derivative


def controlDocking(minimal_publisher, rvecs, tvecs, dockingActionServer):

    #https://www.google.com/search?q=how+to+use+pid+control+system+with+motor&oq=how+to+use+pid+control+system+with+motor&aqs=edge..69i57.14481j0j1&sourceid=chrome&ie=UTF-8#kpvalbx=_6MipYuTPA-2mrgT-0aSQBw36

    """ Controls the docking of the robot from the found aruco marker and its transform and rotational vectors. """

    global completedDocking

    arucoAng = [rvecs[0][0][0], rvecs[0][0][1], rvecs[0][0][2]]
    arucoPos = [tvecs[0][0][0], tvecs[0][0][1], tvecs[0][0][2]]

    # Adjust Z angle
    rad = arucoAng[0]
    print("Rad: " + str(rad))
    angleDiff = rad - targetDockingAng[2]
    pid_angleDiff = PID(angleDiff, 0.001, 0.1, 0.1)
    print("PID angle diff: " + str(pid_angleDiff))
    turnSpeedZ = pid_angleDiff
    if turnSpeedZ > maxTurnSpeed:
        turnSpeedZ = maxTurnSpeed
    elif turnSpeedZ < -maxTurnSpeed:
        turnSpeedZ = -maxTurnSpeed

    # Adjust x position
    distanceX = arucoPos[0] - targetDockingPos[0]
    pid_distanceX = PID(distanceX, 0.3, 0.1, 0.1)
    driveSpeedX = pid_distanceX
    if driveSpeedX > maxSpeedX:
        driveSpeedX = maxSpeedX
    elif driveSpeedX < -maxSpeedX:
        driveSpeedX = -maxSpeedX

    # Adjust z position 
    distanceZ = arucoPos[2] - targetDockingPos[2]
    pid_distanceZ = abs(PID(distanceZ, 0.3, 0.1, 0.1))
    driveSpeedZ = pid_distanceZ
    if driveSpeedZ > maxSpeedZ:
        driveSpeedZ = maxSpeedZ

    if angleDiff > targetDockingAng[2] or pid_distanceX > targetDockingPos[0] or pid_distanceZ > targetDockingPos[2]:
        minimal_publisher.angularVec = (pid_angleDiff, float(pid_angleDiff), -turnSpeedZ)
        #print("turnSpeedZ: ", turnSpeedZ)
        #print("driveSpeedX: ", driveSpeedX)
        #print("driveSpeedZ: ", driveSpeedZ)
        #minimal_publisher.linearVec = (driveSpeedZ, driveSpeedX, 0.0)
        rclpy.spin_once(minimal_publisher)
    else:
        print("Completed docking d8)")
        startFeeder(dockingActionServer)

def startFeeder(dockingActionServer):
    #dockingActionServer.dockSucced = True
    print('Docked!')


def main(args=None):

    global arucoMarkerID

    # Start ROS2 node
    rclpy.init(args=args)

    # Start action server for docking
    action_server = DockingActionServer()

    # Setup PID control in the future maybe?

    while True:
        rclpy.spin(action_server)

    action_server.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
