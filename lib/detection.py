import numpy as np
from tf_utils import visualization_utils_cv2 as vis_util
from lib.webcam import WebcamVideoStream
from lib.session_worker import SessionWorker
from lib.load_graph import LoadFrozenGraph
from lib.load_label_map import LoadLabelMap
from lib.mpvariable import MPVariable
import time
import sys
import cv2
import tensorflow as tf

def without_visualization(category_index, boxes, scores, classes, cur_frame, det_interval, det_th):
    # Exit after max frames if no visualization
    for box, score, _class in zip(np.squeeze(boxes), np.squeeze(scores), np.squeeze(classes)):
        if cur_frame%det_interval==0 and score > det_th:
            label = category_index[_class]['name']
            print("label: {}\nscore: {}\nbox: {}".format(label, score, box))

def visualization(category_index, image, boxes, scores, classes, debug_mode, vis_text, fps_interval):
    # Visualization of the results of a detection.
    vis_util.visualize_boxes_and_labels_on_image_array(
        image,
        np.squeeze(boxes),
        np.squeeze(classes).astype(np.int32),
        np.squeeze(scores),
        category_index,
        use_normalized_coordinates=True,
        line_thickness=8)
    if vis_text:
        if not debug_mode:
            cv2.putText(image,"fps: {:.1f}".format(MPVariable.fps.value), (10,30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (77, 255, 9), 2)
        else:
            """ FOR PERFORMANCE DEBUG """
            cv2.putText(image,"fps: {:.1f} 0.2sec".format(MPVariable.fps_snapshot.value), (10,30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (77, 255, 9), 2)
            cv2.putText(image,"fps: {:.1f} {}sec".format(MPVariable.fps.value, fps_interval), (10,60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (77, 255, 9), 2)
    return image


class SSDMobileNetV1():
    def __init__(self):
        return

    def start(self, cfg):
        """ """ """ """ """ """ """ """ """ """ """
        GET CONFIG
        """ """ """ """ """ """ """ """ """ """ """
        VIDEO_INPUT          = cfg['video_input']
        FORCE_GPU_COMPATIBLE = cfg['force_gpu_compatible']
        VISUALIZE            = cfg['visualize']
        VIS_TEXT             = cfg['vis_text']
        MAX_FRAMES           = cfg['max_frames']
        WIDTH                = cfg['width']
        HEIGHT               = cfg['height']
        FPS_INTERVAL         = cfg['fps_interval']
        DET_INTERVAL         = cfg['det_interval']
        DET_TH               = cfg['det_th']
        SPLIT_MODEL          = cfg['split_model']
        LOG_DEVICE           = cfg['log_device']
        ALLOW_MEMORY_GROWTH  = cfg['allow_memory_growth']
        SSD_SHAPE            = cfg['ssd_shape']
        DEBUG_MODE           = cfg['debug_mode']
        LABEL_PATH           = cfg['label_path']
        NUM_CLASSES          = cfg['num_classes']
        cur_frame = 0
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        LOAD FROZEN_GRAPH
        """ """ """ """ """ """ """ """ """ """ """
        load_frozen_graph = LoadFrozenGraph(cfg)
        graph = load_frozen_graph.load_graph()
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        LOAD LABEL MAP
        """ """ """ """ """ """ """ """ """ """ """
        llm = LoadLabelMap()
        category_index = llm.load_label_map(cfg)
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        PREPARE TF CONFIG OPTION
        """ """ """ """ """ """ """ """ """ """ """
        # Session Config: allow seperate GPU/CPU adressing and limit memory allocation
        config = tf.ConfigProto(allow_soft_placement=True, log_device_placement=LOG_DEVICE)
        config.gpu_options.allow_growth = ALLOW_MEMORY_GROWTH
        config.gpu_options.force_gpu_compatible = FORCE_GPU_COMPATIBLE
        #config.gpu_options.per_process_gpu_memory_fraction = 0.01 # 80MB memory is enough to run on TX2
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        PREPARE GRAPH I/O TO VARIABLE
        """ """ """ """ """ """ """ """ """ """ """
        # Define Input and Ouput tensors
        image_tensor = graph.get_tensor_by_name('image_tensor:0')
        detection_boxes = graph.get_tensor_by_name('detection_boxes:0')
        detection_scores = graph.get_tensor_by_name('detection_scores:0')
        detection_classes = graph.get_tensor_by_name('detection_classes:0')
        num_detections = graph.get_tensor_by_name('num_detections:0')

        if SPLIT_MODEL:
            score_out = graph.get_tensor_by_name('Postprocessor/convert_scores:0')
            expand_out = graph.get_tensor_by_name('Postprocessor/ExpandDims_1:0')
            score_in = graph.get_tensor_by_name('Postprocessor/convert_scores_1:0')
            expand_in = graph.get_tensor_by_name('Postprocessor/ExpandDims_1_1:0')
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        START WORKER THREAD
        """ """ """ """ """ """ """ """ """ """ """
        # gpu_worker uses in split_model and non-split_model
        gpu_tag = 'GPU'
        cpu_tag = 'CPU'
        gpu_worker = SessionWorker(gpu_tag, graph, config)
        if SPLIT_MODEL:
            gpu_opts = [score_out, expand_out]
            cpu_worker = SessionWorker(cpu_tag, graph, config)
            cpu_opts = [detection_boxes, detection_scores, detection_classes, num_detections]
        else:
            gpu_opts = [detection_boxes, detection_scores, detection_classes, num_detections]
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        WAIT UNTIL THE FIRST DUMMY IMAGE DONE
        """ """ """ """ """ """ """ """ """ """ """
        print('Loading...')
        sleep_interval = 0.1
        """
        PUT DUMMY DATA INTO GPU WORKER
        """
        gpu_feeds = {image_tensor:  [np.zeros((300, 300, 3))]}
        gpu_extras = {}
        gpu_worker.put_sess_queue(gpu_opts, gpu_feeds, gpu_extras)
        if SPLIT_MODEL:
            """
            PUT DUMMY DATA INTO CPU WORKER
            """
            if SSD_SHAPE == 600:
                shape = 7326
            else:
                shape = 1917

            score = np.zeros((1, shape, NUM_CLASSES))
            expand = np.zeros((1, shape, 1, 4))
            cpu_feeds = {score_in: score, expand_in: expand}
            cpu_extras = {}
            cpu_worker.put_sess_queue(cpu_opts, cpu_feeds, cpu_extras)
        """
        WAIT UNTIL JIT-COMPILE DONE
        """
        while True:
            g = gpu_worker.get_result_queue()
            if g is None:
                time.sleep(sleep_interval)
            else:
                break
        if SPLIT_MODEL:
            while True:
                c = cpu_worker.get_result_queue()
                if c is None:
                    time.sleep(sleep_interval)
                else:
                    break
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        START CAMERA
        """ """ """ """ """ """ """ """ """ """ """
        video_stream = WebcamVideoStream(VIDEO_INPUT, WIDTH, HEIGHT).start()
        """ """

        """ """ """ """ """ """ """ """ """ """ """
        DETECTION LOOP
        """ """ """ """ """ """ """ """ """ """ """
        print('Starting Detection')
        sleep_interval = 0.005

        try:
            while video_stream.running:
                top_in_time = time.time()
                """
                SPRIT/NON-SPLIT MODEL CAMERA TO WORKER
                """
                if gpu_worker.is_sess_empty(): # must need for speed
                    cap_in_time = time.time()
                    frame = video_stream.read()
                    image_expanded = np.expand_dims(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), axis=0) # np.expand_dims is faster than []
                    #image_expanded = np.expand_dims(frame, axis=0) # BGR image for input. Of couse, bad accuracy in RGB trained model, but speed up.
                    cap_out_time = time.time()
                    # put new queue
                    gpu_feeds = {image_tensor: image_expanded}
                    if VISUALIZE:
                        gpu_extras = {'image':frame, 'top_in_time':top_in_time, 'cap_in_time':cap_in_time, 'cap_out_time':cap_out_time} # for visualization frame
                    else:
                        gpu_extras = {'top_in_time':top_in_time, 'cap_in_time':cap_in_time, 'cap_out_time':cap_out_time}
                    gpu_worker.put_sess_queue(gpu_opts, gpu_feeds, gpu_extras)

                g = gpu_worker.get_result_queue()
                if SPLIT_MODEL:
                    # if g is None: gpu thread has no output queue. ok skip, let's check cpu thread.
                    if g:
                        # gpu thread has output queue.
                        score, expand, extras = g['results'][0], g['results'][1], g['extras']

                        if cpu_worker.is_sess_empty():
                            # When cpu thread has no next queue, put new queue.
                            # else, drop gpu queue.
                            cpu_feeds = {score_in: score, expand_in: expand}
                            cpu_extras = extras
                            cpu_worker.put_sess_queue(cpu_opts, cpu_feeds, cpu_extras)
                        # else: cpu thread is busy. don't put new queue. let's check cpu result queue.
                    # check cpu thread.
                    q = cpu_worker.get_result_queue()
                else:
                    """
                    NON-SPLIT MODEL
                    """
                    q = g
                if q is None:
                    """
                    SPLIT/NON-SPLIT MODEL
                    """
                    # detection is not complete yet. ok nothing to do.
                    time.sleep(sleep_interval)
                    continue

                """
                VISUALIZATION
                """
                vis_in_time = time.time()
                boxes, scores, classes, num, extras = q['results'][0], q['results'][1], q['results'][2], q['results'][3], q['extras']

                if VISUALIZE:
                    image = extras['image']
                    # Visualization of the results of a detection.
                    image = visualization(category_index, image, boxes, scores, classes, DEBUG_MODE, VIS_TEXT, FPS_INTERVAL)
                    """
                    SHOW
                    """
                    cv2.imshow("Object Detection", image)
                    # Press q to quit
                    if cv2.waitKey(1) & 0xFF == 113: #ord('q'):
                        MPVariable.running.value = False
                        break
                else:
                    """
                    NO VISUALIZE
                    """
                    without_visualization(category_index, boxes, scores, classes, cur_frame, DET_INTERVAL, DET_TH)


                vis_out_time = time.time()


                """
                PROCESSING TIME
                """
                top_in_time = extras['top_in_time']
                cap_proc_time = extras['cap_out_time'] - extras['cap_in_time']
                gpu_proc_time = extras[gpu_tag+'_out_time'] - extras[gpu_tag+'_in_time']
                if SPLIT_MODEL:
                    cpu_proc_time = extras[cpu_tag+'_out_time'] - extras[cpu_tag+'_in_time']
                else:
                    cpu_proc_time = 0
                vis_proc_time = vis_out_time - vis_in_time
                lost_proc_time = vis_out_time - top_in_time - cap_proc_time - gpu_proc_time - cpu_proc_time - vis_proc_time
                total_proc_time = vis_out_time - top_in_time
                MPVariable.cap_proc_time.value += cap_proc_time
                MPVariable.gpu_proc_time.value += gpu_proc_time
                MPVariable.cpu_proc_time.value += cpu_proc_time
                MPVariable.vis_proc_time.value += vis_proc_time
                MPVariable.lost_proc_time.value += lost_proc_time
                MPVariable.total_proc_time.value += total_proc_time

                if DEBUG_MODE:
                    if SPLIT_MODEL:
                        sys.stdout.write('snapshot FPS:{: ^5.1f} total:{: ^10.5f} cap:{: ^10.5f} gpu:{: ^10.5f} cpu:{: ^10.5f} vis:{: ^10.5f} lost:{: ^10.5f}\n'.format(
                            MPVariable.fps.value, total_proc_time, cap_proc_time, gpu_proc_time, cpu_proc_time, vis_proc_time, lost_proc_time))
                    else:
                        sys.stdout.write('snapshot FPS:{: ^5.1f} total:{: ^10.5f} cap:{: ^10.5f} gpu:{: ^10.5f}  vis:{: ^10.5f} lost:{: ^10.5f}\n'.format(
                            MPVariable.fps.value, total_proc_time, cap_proc_time, gpu_proc_time, vis_proc_time, lost_proc_time))
                """ """

                """
                EXIT WITHOUT GUI
                """
                if not VISUALIZE:
                    if cur_frame >= MAX_FRAMES:
                        MPVariable.running.value = False
                        break
                    cur_frame += 1
                """
                CHANGE SLEEP INTERVAL
                """
                if MPVariable.frame_counter.value == 0 and MPVariable.fps.value > 0:
                    sleep_interval = 0.05 / MPVariable.fps.value
                    MPVariable.sleep_interval.value = sleep_interval

                MPVariable.frame_counter.value += 1
            """
            END while
            """
        except:
            import traceback
            traceback.print_exc()

        finally:
            """ """ """ """ """ """ """ """ """ """ """
            CLOSE
            """ """ """ """ """ """ """ """ """ """ """
            MPVariable.running.value = False
            gpu_worker.stop()
            if SPLIT_MODEL:
                cpu_worker.stop()
            video_stream.stop()

            if VISUALIZE:
                cv2.destroyAllWindows()
            """ """

        return
    
