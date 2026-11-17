from manim import *
from manim_slides import Slide


class Deck(Slide):
    pass


class Welcome(Deck):
    def construct(self):
        self.add(Text("X11 smoke"))


class Shapes(Deck):
    def construct(self):
        self.add(Circle(), Text("Shapes"))
