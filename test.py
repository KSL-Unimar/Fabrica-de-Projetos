from ultralytics import YOLO

model = YOLO("yolo26n.pt")

results = model.track(source="https://www.youtube.com/watch?v=mWxjRXR7nWI", show=True)