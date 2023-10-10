import PIL.Image
from luma.core.render import canvas
from luma.core.device import dummy

class StubOLED:
    device: dummy

    def set_data_window(self, x: int, y: int , width: int, height: int):
        self.device = dummy(height=int(height), width=int(width))
        pass

    def Write_Instruction(self, data):
        pass

    def writeDataBytes(self, data):
      with canvas(self.device) as draw:
        draw.text([10,10], "foobar")
      pass

    def getImage(self) -> PIL.Image.Image:
       return self.device.image

