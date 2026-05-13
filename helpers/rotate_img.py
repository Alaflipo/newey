from PIL import Image

img = Image.open("milan.png")
rotated = img.rotate(45, expand=True)
rotated.save("rotate.png")
