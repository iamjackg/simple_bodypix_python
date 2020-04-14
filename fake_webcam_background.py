#!/usr/bin/env python3
import cv2
import sys
from PIL import Image
import tfjs_graph_converter as tfjs
import tensorflow as tf
import math
import matplotlib.patches as patches
import numpy as np
import os
import pyfakewebcam

# make tensorflow stop spamming messages
#os.environ['TF_CPP_MIN_LOG_LEVEL'] = "3"

cap = cv2.VideoCapture('/dev/video0')

# configure camera for 720p @ 30 FPS
height, width = 720, 1280
cap.set(cv2.CAP_PROP_FRAME_WIDTH ,width)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT,height)
cap.set(cv2.CAP_PROP_FPS, 30)

fakewebcam = pyfakewebcam.FakeWebcam("/dev/video2", width, height)

# CONSTANTS
OutputStride = 16
internalResolution = 0.5

# PATHS
modelPath = 'bodypix_mobilenet_float_{0:03d}_model-stride{1}'.format(
    int(100*internalResolution), OutputStride)

segmentation_threshold = 0.7
dilate_value = 0
blur_radius = 30

#tf.debugging.set_log_device_placement(True)

print("Loading model...")
graph = tfjs.api.load_graph_model(modelPath)  # downloaded from the link above
print("done.")

replacement_bg = None
replacement_bg_mtime = 0

def load_replacement_bg(replacement_bg):
    if os.stat("background.jpg").st_mtime != replacement_bg_mtime:
        replacement_bg_raw = cv2.imread("background.jpg")
        replacement_bg = cv2.resize(replacement_bg_raw, (width, height))
        replacement_bg = replacement_bg[...,::-1]
    return replacement_bg

sess = tf.compat.v1.Session(graph=graph)
input_tensor_names = tfjs.util.get_input_tensors(graph)
output_tensor_names = tfjs.util.get_output_tensors(graph)
input_tensor = graph.get_tensor_by_name(input_tensor_names[0])

def isValidInputResolution(resolution, outputStride):
    return (resolution - 1) % outputStride == 0;

def toValidInputResolution(inputResolution, outputStride):
    if isValidInputResolution(inputResolution, outputStride):
        return inputResolution
    return int(np.floor(inputResolution / outputStride) * outputStride + 1)

def toInputResolutionHeightAndWidth(internalResolution, outputStride, inputHeight, inputWidth):
    return (toValidInputResolution(inputHeight * internalResolution, outputStride),
            toValidInputResolution(inputWidth * internalResolution, outputStride))

while True:
    success, frame = cap.read()
    if not success:
        print("Error getting a webcam image!")
        sys.exit(1)

    replacement_bg = load_replacement_bg(replacement_bg)

    frame = frame[...,::-1]

    img = Image.fromarray(frame)
    imgWidth, imgHeight = img.size

    #targetWidth = (int(imgWidth) // OutputStride) * OutputStride + 1
    #targetHeight = (int(imgHeight) // OutputStride) * OutputStride + 1

    targetWidth, targetHeight = toInputResolutionHeightAndWidth(
        internalResolution, OutputStride, imgWidth, imgHeight)

    img = img.resize((targetWidth, targetHeight))
    x = tf.keras.preprocessing.image.img_to_array(img, dtype=np.float32)
    InputImageShape = x.shape

    widthResolution = int((InputImageShape[1] - 1) / OutputStride) + 1
    heightResolution = int((InputImageShape[0] - 1) / OutputStride) + 1

    # add imagenet mean - extracted from body-pix source
    m = np.array([-123.15, -115.90, -103.06])
    x = np.add(x, m)
    x = np.divide(x, 127.5)
    x = np.subtract(x, 1.0)
    sample_image = x[tf.newaxis, ...]

    results = sess.run(output_tensor_names, feed_dict={
                       input_tensor: sample_image})
    segments = np.squeeze(results[1], 0)

    # Segmentation MASK
    segmentScores = tf.sigmoid(segments)
    #segmentScores = segments
    #print(segmentScores[0,0], segmentScores.min(), segmentScores.max())
    #print(segmentScores[0,0])
    mask = tf.math.greater(segmentScores, tf.constant(segmentation_threshold))
    #print(mask.shape)
    segmentationMask = tf.dtypes.cast(mask, tf.int32)
    segmentationMask = np.reshape(
        segmentationMask, (segmentationMask.shape[0], segmentationMask.shape[1]))

    # Draw Segmented Output
    mask_img = Image.fromarray(segmentationMask * 255)
    mask_img = mask_img.resize(
        (width, height), Image.LANCZOS).convert("RGB")
    mask_img = tf.keras.preprocessing.image.img_to_array(
        mask_img, dtype=np.uint8)

    mask_img = cv2.dilate(mask_img, np.ones((dilate_value, dilate_value), np.uint8), iterations=1)
    mask_img = cv2.blur(mask_img, (blur_radius, blur_radius))
    segmentationMask_inv = np.bitwise_not(mask_img)

    #frame = frame[...,::-1] # convert frame back to BGR
    #frame = np.bitwise_and(frame, mask_img[:,:,:]) + \
    #        np.bitwise_and(replacement_bg, segmentationMask_inv[:,:,:])
    for c in range(3):
        frame[:,:,c] = frame[:,:,c] * (mask_img[:,:,0] / 255.) + \
            replacement_bg[:,:,c] * (1.0-(mask_img[:,:,0] / 255.))

    #frame = np.array(segmentationMask_inv[:,:,:])
    fakewebcam.schedule_frame(frame)

sys.exit(0)
