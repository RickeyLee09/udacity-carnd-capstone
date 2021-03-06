from styx_msgs.msg import TrafficLight

import rospy
import cv2
import tensorflow as tf
import numpy as np
from PIL import Image
from PIL import ImageDraw
from PIL import ImageColor
from datetime import datetime

SSD_GRAPH_FILE = 'ssd_mobilenet_v1_coco_11_06_2017/frozen_inference_graph.pb'
TARGET_CLASS = 10  ## traffic light

IS_OUTPUT_IMAGE = False

boundaries = [
    ([0, 100, 80], [10, 255, 255]), # red
    ([18, 0, 196], [36, 255, 255]), # yellow
    ([36, 202, 59], [71, 255, 255]) # green
]

COLOR_LIST = ['red', 'yellow', 'green']

def filter_boxes(min_score, target_class, boxes, scores, classes):
    """Return boxes with a confidence >= `min_score`"""
    n = len(classes)
    idxs = []
    for i in range(n):
        if scores[i] >= min_score and classes[i] == target_class:
            idxs.append(i)
 
    filtered_boxes = boxes[idxs, ...]
    filtered_scores = scores[idxs, ...]
    filtered_classes = classes[idxs, ...]
    return filtered_boxes, filtered_scores, filtered_classes

def to_image_coords(boxes, height, width):
    """
    The original box coordinate output is normalized, i.e [0, 1].
 
    This converts it back to the original coordinate based on the image
    size.
    """
    box_coords = np.zeros_like(boxes)
    box_coords[:, 0] = boxes[:, 0] * height
    box_coords[:, 1] = boxes[:, 1] * width
    box_coords[:, 2] = boxes[:, 2] * height
    box_coords[:, 3] = boxes[:, 3] * width

    return box_coords

def draw_boxes(image, boxes, classes, scores, color_id, thickness=4):
    """Draw bounding boxes on the image"""
    draw = ImageDraw.Draw(image)
    for i in range(len(boxes)):
        bot, left, top, right = boxes[i, ...]
        class_id = int(classes[i])
        color = COLOR_LIST[color_id]
        
        draw.line([(left, top), (left, bot), (right, bot), (right, top), (left, top)], width=thickness, fill=color)
        draw.rectangle([(left, bot-20), (right, bot)], outline=color, fill=color)
        draw.text((left, bot-15), str(scores[i]), 'black')

def load_graph(graph_file):
    """Loads a frozen inference graph"""
    graph = tf.Graph()
    with graph.as_default():
        od_graph_def = tf.GraphDef()
        with tf.gfile.GFile(graph_file, 'rb') as fid:
            serialized_graph = fid.read()
            od_graph_def.ParseFromString(serialized_graph)
            tf.import_graph_def(od_graph_def, name='')
    return graph

class TLClassifier(object):
    def __init__(self):
        #TODO load classifier
        rospy.logwarn("load model file: %s", SSD_GRAPH_FILE)
        self.detection_graph = load_graph(SSD_GRAPH_FILE)

        # The input placeholder for the image.
        # `get_tensor_by_name` returns the Tensor with the associated name in the Graph.
        self.image_tensor = self.detection_graph.get_tensor_by_name('image_tensor:0')

        # Each box represents a part of the image where a particular object was detected.
        self.detection_boxes = self.detection_graph.get_tensor_by_name('detection_boxes:0')

        # Each score represent how level of confidence for each of the objects.
        # Score is shown on the result image, together with the class label.
        self.detection_scores = self.detection_graph.get_tensor_by_name('detection_scores:0')

        # The classification of the object (integer id).
        self.detection_classes = self.detection_graph.get_tensor_by_name('detection_classes:0')

        with tf.Session(graph=self.detection_graph) as sess:
            self.session = sess

    def get_classification(self, image):
        """Determines the color of the traffic light in the image
        Args:
            image (cv::Mat): image containing the traffic light
        Returns:
            int: ID of traffic light color (specified in styx_msgs/TrafficLight)
        """
        #TODO implement light color prediction
        color = TrafficLight.UNKNOWN
        
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image_np = np.expand_dims(np.asarray(image, dtype=np.uint8), 0)
              
        # Actual detection.
        (boxes, scores, classes) = self.session.run([self.detection_boxes, self.detection_scores, self.detection_classes], 
                                            feed_dict={self.image_tensor: image_np})

        # Remove unnecessary dimensions
        boxes = np.squeeze(boxes)
        scores = np.squeeze(scores)
        classes = np.squeeze(classes)

        confidence_cutoff = 0.2
        # Filter boxes with a confidence score less than `confidence_cutoff`
        boxes, scores, classes = filter_boxes(confidence_cutoff, TARGET_CLASS, boxes, scores, classes)

        if len(boxes) > 0:
            # The current box coordinates are normalized to a range between 0 and 1.
            # This converts the coordinates actual location on the image.
            width, height = image.shape[-2::-1]
            box_coords = to_image_coords(boxes, height, width)

            ryg = [0,0,0]
            for i in range(len(box_coords)):
                bot, left, top, right = box_coords[i, ...]
                box_img = image[int(bot):int(top), int(left):int(right), :]

                box_img = cv2.GaussianBlur(box_img, (3, 3), 0)

                hsv = cv2.cvtColor(box_img, cv2.COLOR_RGB2HSV)
                mask = [0,0,0]
                box_height = hsv.shape[0]
                box_width = hsv.shape[1]
                if box_height < box_width:  ## simulation mode
                    for j, (lower, upper) in enumerate(boundaries):
                        # create NumPy arrays from the boundaries
                        lower = np.array(lower, dtype = "uint8")
                        upper = np.array(upper, dtype = "uint8")

                        # find the colors within the specified boundaries and apply
                        # the mask
                        mask[j] = sum(np.hstack(cv2.inRange(hsv, lower, upper)))
                else:  ## real life mode
                    v = hsv[:,:,2]

                    top_v = np.sum(v[:int(box_height/3),:])
                    middle_v = np.sum(v[int(box_height/3):int(box_height*2/3),:])
                    bottom_v = np.sum(v[int(box_height*2/3):,:])
                    max_v = max(top_v,middle_v,bottom_v)
 
                    if max_v != 0:
                        for idx, item in enumerate([top_v, middle_v, bottom_v]):
                            if item / max_v == 1:
                                mask[idx] = 1
                                break
                    else:
                        mask = [1, 0, 0]  # default red

                ryg[mask.index(max(mask))] += 1 

            color = ryg.index(max(ryg))

            if IS_OUTPUT_IMAGE:
                image_file = '../../../imgs/' + str(datetime.now()) + '.png'
                # Each class with be represented by a differently colored box
                draw_img = Image.fromarray(image)
                draw_boxes(draw_img, box_coords, classes ,scores, color)
                draw_img.save(image_file)

        rospy.logwarn('detected light = %d', color)
        return color