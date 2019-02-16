# Copyright (C) 2018 Christopher Gearhart
# chris@bblanimation.com
# http://bblanimation.com/
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# System imports
import time

# Blender imports
import bpy

# Addon imports
from ..addon_common.cookiecutter.cookiecutter import CookieCutter
from ..addon_common.common import ui
from ..addon_common.common.decorators import PersistentOptions
from ..functions import *

@PersistentOptions()
class WaxDropperOptions:
    defaults = {
        "action": "add",
        "blob_size": 1.0,
        "paint_radius":2.0,
        "position": 9,
        "resolution":0.4,
        "surface_target": "object",  #object, object_wax
    }


class WaxDrop_States():

    #############################################
    # State keymap

    default_keymap = {
        "sketch":     {"LEFTMOUSE"},
        "remove wax": {"SHIFT+LEFTMOUSE"},
        "painting":   {"ALT+LEFTMOUSE"},
        "commit":     {"RET"},
        "cancel":     {"ESC"},
    }

    #############################################
    # State functions

    @CookieCutter.FSM_State("main")
    def modal_main(self):
        self.cursor_modal_set("CROSSHAIR")

        if self.actions.pressed("remove wax"):
            self.perform_wax_action(delete_wax=True)
            return

        if self.actions.pressed("sketch"):
            return "sketch"

        if self.actions.alt:
            return "paint wait"

        if self.actions.pressed("commit"):
            self.done();
            return

        if self.actions.pressed("cancel"):
            self.done(cancel=True)
            return

    #--------------------------------------
    # sketch

    @CookieCutter.FSM_State("sketch", "can enter")
    def can_enter_sketch(self):
        # if self.wax_opts["surface_target"] == "object":
        #     return self.ray_cast_source_hit(self.actions.mouse)
        # else:
        #     # TODO: potentially check for ray cast hit on wax object
        return True

    @CookieCutter.FSM_State("sketch", "enter")
    def enter_sketch(self):
        self.sketcher.add_loc(*self.actions.mouse)
        if self.wax_opts["surface_target"] == "object_wax":
            self.net_ui_context_wax.update_bvh()

    @CookieCutter.FSM_State("sketch")
    def modal_sketch(self):
        if self.actions.mousemove:
            self.sketcher.smart_add_loc(*self.actions.mouse)
        if self.actions.released('sketch'):
            return 'main'

    @CookieCutter.FSM_State("sketch", "exit")
    def end_sketch(self):
        # return if a single point was drawn
        # if not self.sketcher.is_good():
        #     return
        # Simplify sketch into uniformly spaced locs
        new_locs = self.sketcher.finalize_uniform(self.context, self.net_ui_context if self.wax_opts["surface_target"] == "object" else self.net_ui_context_wax,  step_size=self.wax_opts["blob_size"] * 0.75, error_threshold=0.1)
        # add metaballs at uniformly spaced locs
        for loc in new_locs:
            self.draw_wax(loc)
            self.push_meta_to_wax()
        # reset the sketcher object for next time
        self.sketcher.reset()

    #--------------------------------------
    # paint wait

    @CookieCutter.FSM_State('paint wait', 'can enter')
    def region_paint_wait_can_enter(self):
        return True

    @CookieCutter.FSM_State('paint wait', 'enter')
    def region_paint_wait_enter(self):
        self.brush = self.PaintBrush(self.net_ui_context, radius=self.wax_opts["paint_radius"])
        self.brush_density()

    @CookieCutter.FSM_State('paint wait')
    def region_paint_wait(self):
        self.cursor_modal_set('PAINT_BRUSH')

        if not self.actions.alt:
            return 'main'

        if self.event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN'}:
            if self.event.type == 'TRACKPADPAN':
                move = self.event.mouse_y - self.event.mouse_prev_y
            else:
                move = self.drawing.scale(24) * (-1 if 'UP' in self.event.type else 1)
            self.wax_opts["paint_radius"] = max(0, self.wax_opts["paint_radius"] + (move/100))
            self.brush.radius = self.wax_opts["paint_radius"]
            self.brush_density()

        if self.actions.pressed('painting'):
            return 'painting'

    @CookieCutter.FSM_State('paint wait', 'exit')
    def region_paint_wait_exit(self):
        pass

    #--------------------------------------
    # painting

    @CookieCutter.FSM_State('painting', 'can enter')
    def region_painting_can_enter(self):
        #any time really, may require a BVH update if
        #network cutter has been executed
        return True

    @CookieCutter.FSM_State('painting', 'enter')
    def region_painting_enter(self):
        # set the cursor to to something
        # self.network_cutter.find_boundary_faces_cycles()
        self.click_enter_paint()
        self.last_loc = None
        self.last_update = 0
        self.paint_dirty = False

    @CookieCutter.FSM_State('painting')
    def region_painting(self):
        self.cursor_modal_set('PAINT_BRUSH')

        if self.actions.released('painting'):
            return 'paint wait' if self.actions.alt else 'main'

        loc,norm,_ = self.brush.ray_hit(self.actions.mouse, self.context)
        if loc and (not self.last_loc or (self.last_loc - loc).length > self.brush.radius/4):
            self.last_loc = loc
            #self.brush.absorb_geom(self.context, self.actions.mouse)
            self.paint_dirty = True
            # paint the particles
            spiral_points_3d = self.brush.spiral_points_to_3d(loc, norm)
            for loc0 in spiral_points_3d:
                result, loc1, norm, _ = self.source.closest_point_on_mesh(loc0, distance=self.brush.radius/2)
                # TODO: throw away results with normal facing away from view (backfaces)
                self.draw_wax(loc1)
            self.draw_wax(loc)
            self.push_meta_to_wax()



        if self.paint_dirty and (time.time() - self.last_update) > 0.2:
            self.paint_dirty = False
            self.last_update = time.time()

    @CookieCutter.FSM_State('painting', 'exit')
    def region_painting_exit(self):
        # TODO: finish the particle painting
        pass

    # #--------------------------------------
    # # paint delete
    #
    # @CookieCutter.FSM_State('paint delete', 'enter')
    # def region_unpaint_enter(self):
    #     #set the cursor to to something
    #     # self.network_cutter.find_boundary_faces_cycles()
    #     self.click_enter_paint(delete = True)
    #     self.last_loc = None
    #     self.last_update = 0
    #     self.paint_dirty = False
    #
    # @CookieCutter.FSM_State('paint delete')
    # def region_unpaint(self):
    #     self.cursor_modal_set('PAINT_BRUSH')
    #
    #     if self.actions.released('RIGHTMOUSE'):
    #         return 'main'
    #
    #     loc,_,_ = self.brush.ray_hit(self.actions.mouse, self.context)
    #     if loc and (not self.last_loc or (self.last_loc - loc).length > self.brush.radius*(0.25)):
    #         self.last_loc = loc
    #         #self.brush.absorb_geom(self.context, self.actions.mouse)
    #         self.paint_dirty = True
    #         # TODO: actually remove the particles
    #
    #     if self.paint_dirty and (time.time() - self.last_update) > 0.2:
    #         self.paint_dirty = False
    #         self.last_update = time.time()
    #
    # @CookieCutter.FSM_State('paint delete', 'exit')
    # def region_unpaint_exit(self):
    #     # TODO: finish removing the particles
    #     pass

    #############################################
