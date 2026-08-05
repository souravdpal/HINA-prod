from ultralytics import YOLO
import cv2
import torch

# Limit CPU threads (adjust if needed)
torch.set_num_threads(4)

# Load YOLO Nano
#model = YOLO("yolo11n.pt")
model = YOLO("yolo11s.pt")
# Webcam
cap = cv2.VideoCapture(0)

# Try to reduce webcam buffering (works on many systems)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

CONFIDENCE = 0.5
FRAME_SKIP = 3  # Run YOLO every 3rd frame

frame_count = 0
last_objects = set()
last_result = None

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1

    # Run YOLO only every FRAME_SKIP frames
    if frame_count % FRAME_SKIP == 0:
        results = model(
            frame,
            imgsz=320,
            conf=CONFIDENCE,
            verbose=False
        )

        last_result = results[0]

        current_objects = set()

        for box in last_result.boxes:
            cls = int(box.cls[0])
            current_objects.add(model.names[cls])

        # Print only if objects changed
        if current_objects != last_objects:
            if current_objects:
                print("Detected:", ", ".join(sorted(current_objects)))
            else:
                print("Nothing detected")

            last_objects = current_objects

    # Show latest detection result
    if last_result is not None:
        display = last_result.plot()
    else:
        display = frame

    cv2.imshow("YOLO11 Nano", display)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
