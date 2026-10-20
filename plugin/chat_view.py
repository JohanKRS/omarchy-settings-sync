"""Follow laid-out chat text and provide a small elastic edge movement."""
from __future__ import annotations

from gi.repository import Gdk, GLib, Graphene, Gtk


class ElasticMessages(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.offset = 0.0

    def do_snapshot(self, snapshot):
        snapshot.save()
        snapshot.translate(Graphene.Point().init(0, self.offset))
        Gtk.Box.do_snapshot(self, snapshot)
        snapshot.restore()


class ChatView(Gtk.ScrolledWindow):
    def __init__(self):
        super().__init__(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.add_css_class('chat-scroll')
        self.messages = ElasticMessages()
        self.messages.set_margin_bottom(12)
        self.set_child(self.messages)
        self.follow_tail = True
        self.aligning = False
        self.layout_idle = None
        self.velocity = 0.0
        self.tick = None
        self.last_frame = None
        adjustment = self.get_vadjustment()
        adjustment.connect('changed', self.layout_changed)
        adjustment.connect('value-changed', self.position_changed)
        controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect('scroll', self.scroll_edge)
        self.add_controller(controller)
        self.connect('unmap', lambda *_: self.reset_elastic())

    def layout_changed(self, *_):
        # GtkViewport is still allocating its child when the range changes.
        # Adjust afterwards so the child's transform uses the new position.
        if self.layout_idle is None:
            self.layout_idle = GLib.idle_add(self.follow_layout)

    def follow_layout(self):
        self.layout_idle = None
        self.to_end()
        return False

    def to_end(self, *, force=False):
        if force:
            self.follow_tail = True
        if self.follow_tail:
            adjustment = self.get_vadjustment()
            self.aligning = True
            adjustment.set_value(max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size()))
            self.aligning = False

    def position_changed(self, adjustment):
        if not self.aligning:
            self.follow_tail = adjustment.get_value() >= adjustment.get_upper() - adjustment.get_page_size() - 2

    def scroll_edge(self, controller, _dx, dy):
        adjustment = self.get_vadjustment()
        lower, upper = adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size()
        value = adjustment.get_value()
        if upper <= lower or not ((dy < 0 and value <= lower + .5) or (dy > 0 and value >= upper - .5)):
            self.reset_elastic()
            return False
        # Move the content itself, instead of drawing GTK's edge glow. Leave
        # ordinary scrolling, touch gestures and scrollbar behavior to GTK.
        scale = 14 if controller.get_unit() == Gdk.ScrollUnit.WHEEL else 1.5
        self.pull(-dy * scale)
        return True

    def pull(self, distance):
        if not self.get_settings().get_property('gtk-enable-animations'):
            return
        offset = self.messages.offset
        self.messages.offset = max(-28, min(28, offset + distance / (1 + abs(offset) / 10)))
        self.messages.queue_draw()
        self.velocity = 0.0
        if self.tick is None:
            self.last_frame = None
            self.tick = self.add_tick_callback(self.spring_frame)

    def spring_frame(self, _widget, clock):
        now = clock.get_frame_time()
        dt = min(.033, (now - self.last_frame) / 1_000_000) if self.last_frame else 1 / 60
        self.last_frame = now
        self.velocity += (-200 * self.messages.offset - 26 * self.velocity) * dt
        self.messages.offset += self.velocity * dt
        if abs(self.messages.offset) < .1 and abs(self.velocity) < .5:
            self.messages.offset = self.velocity = 0.0
            self.tick = None
            self.messages.queue_draw()
            return False
        self.messages.queue_draw()
        return True

    def reset_elastic(self):
        if self.tick is not None:
            self.remove_tick_callback(self.tick)
            self.tick = None
        self.messages.offset = self.velocity = 0.0
        self.messages.queue_draw()
