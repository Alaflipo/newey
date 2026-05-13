import math

from PySide6.QtWidgets import QWidget, QSizePolicy, QMenu, QMessageBox, QFileDialog
from PySide6.QtGui import QPainter, QPixmap, QColor, Qt, QTransform, QVector2D, QPolygonF, QImage, QPainterPath, QPointingDevice
from PySide6.QtCore import QPointF, QEvent, QSize, QRectF

from io_management.fileformat_loom import read_network_from_loom, export_loom, render_loom, example_network, add_edge, empty_network
from io_management.fileformat_graphml import read_network_from_graphml
from io_management.fileformat_newey import write_newey_file, read_newey_file, get_unique_filename

from helpers.layout import layout_lp
import helpers.port_assign as pa

from elements.network import Label, Node, Edge, Network
from elements.group import Group

import random
import pickle

import render
import ui

min_edge_scale = 80

diag = 1/math.sqrt(2)
port_offset = [ QPointF(-1,0)
              , QPointF(-diag,diag)
              , QPointF(0,1)
              , QPointF(diag,diag)
              , QPointF(1,0)
              , QPointF(diag,-diag)
              , QPointF(0,-1)
              , QPointF(-diag,-diag)
              ]

class Canvas(QWidget):
    def __init__(self, history_checkpoint):
        super().__init__()
        self.pixmap = QPixmap( self.size() )
        self.pixmap.fill( QColor('white') )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.grabGesture(Qt.PinchGesture)

        # to create a history checkpoint
        self.history_checkpoint = history_checkpoint

        self.station_added = 0
        self.there_was_change = False 

        # UI state
        self.old_mouse = None
        self.view = QTransform()
        self.drag = False 

        # load a network
        self.filename = 'loom-examples/wien.json'
        self.network, self.filedata = read_network_from_loom(self.filename)
        # self.network = example_network()
        # self.network = empty_network()
        self.network.scale_by_shortest_edge( min_edge_scale )
        self.network.find_degree_2_lines()
        self.network.calculate_mid_point()
        self.network.find_min_max_geo()
        self.network.divide_in_lines()
       
        self.label_dist:int = 25

        self.affected_nodes: list[Node] = []
        
        self.selection_path: QPolygonF = QPolygonF()
        self.brush: QPainterPath = QPainterPath()
        
        self.drag_group: bool = False
        self.move_group: bool = False 
        self.expand_group: bool = False 
        self.lock_group: bool = False 
        self.label_group: bool = False 
        self.shape_group: bool = False 
        self.pivot_group: int | None = None 

        self.groups: dict[str, Group] = {}
        self.group: Group | None = None
        
        # 0 = square, 1 = lasso, 2 = brush, 3 = line 
        self.selection_mode: int = 1
        self.color_selected: None | str = None 

        self.error_message: None | str = None 
        
    def render(self):
        #self.network.clone()
        painter = QPainter(self.pixmap)
        self._render(painter, self.view)
        self.update()

    def _render(self, painter, view, export=False):
        painter.setRenderHint(QPainter.Antialiasing)
        # viewport
        painter.setTransform(view)
        # draw
        self.pixmap.fill( QColor('white') )
        ui.update_params( view.m11() ) # element [1,1] of the view matrix is scale in our case
        
        render.render_network(painter, self.network, self.show_background.isChecked(), self.label_dist, self.group, export=export)
        
        if self.group: 
            render.render_group(painter, self.group, self.move_group, self.pivot_group)
        else: 
            if self.selection_mode == 0: render.render_rectangle_select(painter, self.selection_path)
            elif self.selection_mode == 1: render.render_lasso(painter, self.selection_path)
            elif self.selection_mode == 2: render.render_brush(painter, self.selection_path, self.brush)

        # render.render_concentric_circles(painter)
        render.render_highlighted_nodes(painter, self.affected_nodes)

        if self.error_message != None: 
            render.render_error_message(painter, view, self.error_message)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)
		
    def zoom_to_network(self):
        min_x, min_y = math.inf, math.inf
        max_x, max_y = -math.inf, -math.inf
        for name, v in self.network.nodes.items():
            min_x = min(min_x, v.pos.x())
            min_y = min(min_y, v.pos.y())
            max_x = max(max_x, v.pos.x())
            max_y = max(max_y, v.pos.y())
        x_scale = (0.9*self.width()) / (max_x - min_x)
        y_scale = (0.9*self.height()) / (max_y - min_y)
        scale = min(x_scale, y_scale)
        self.view = QTransform()
        self.view.translate(0.05*self.width(), 0.05*self.height())
        self.view.scale(scale, scale)
        self.view.translate(-min_x, -min_y)
    
    def worldspace(self, pos):
        return self.view.inverted()[0].map(QPointF(pos))
	
    def resizeEvent(self, event):
        if self.size() != self.pixmap.size():
            new_pixmap = QPixmap(self.size())
            new_pixmap.fill(QColor('white'))
            painter = QPainter(new_pixmap)
            self.render()
            painter.drawPixmap(0, 0, self.pixmap)
            self.pixmap = new_pixmap

    def drawing_is_completely_oob(self):
        # Is any node on the canvas based on the viewport? (Ignores edges.)
        rect = self.rect()
        for v in self.network.nodes.values():
            p = self.view.map(v.pos).toPoint()
            if rect.contains(p): return False
        return True
    
    def add_group(self, id: str, text: str, color: str | None = None) -> bool: 
        if not self.group: return False 

        self.group.name = text 
        self.group.color = color 
        self.groups[id] = self.group
        return True 

    def create_groups_from_lines(self): 
        self.groups = {}
        for i, color in enumerate(self.network.lines): 
            nodes = self.network.lines[color]

            # Create a group 
            self.groups[color] = Group(nodes, name=color, color=f'#{color}')


    # Forward every mouse event to the function handle_mouse 
    def mousePressEvent(self, event): self.handle_mouse(event,press=True)
    def mouseReleaseEvent(self, event): self.handle_mouse(event,release=True)
    def mouseMoveEvent(self, event): self.handle_mouse(event)
    def mouseDoubleClickEvent(self, event): self.handle_mouse(event,doubleclick=True)
    def handle_mouse(self,event, press=False, release=False, doubleclick=False):
        
        # For undo message: what did we change about the network, if anything?
        self.network_change = None 

        # Check what the current mouse position is
        self.mouse_pos, self.event_pos = None, None 
        self.event_pos = event.position()
        self.mouse_pos = self.worldspace(self.event_pos)
        
        # Check where the mouse pointer is close to 
        self.handle_currently_hovering()

        ##### Handle panning of the view #####
        if event.buttons() == Qt.MiddleButton and self.old_mouse:
            self.handle_pan(event)

        ##### Handle everything by right click #####
        if event.buttons() == Qt.RightButton:
            # context menu for if an edge has been right clicked 
            if ui.hover_edge:
                self.handle_menu_edge()
            # context menu for if only a node has been right clicked 
            elif ui.hover_node and ui.hover_empty_port is None:
                self.handle_menu_node()

        ##### Handle everything by left click #####
        if press and event.buttons() == Qt.LeftButton:
            # Both start dragging and port selection 
            self.handle_single_left_click()
        if release: 
            # Both end dragging and port selection
            self.handle_release(event)
        if doubleclick: 
            self.handle_double_click()

        ### Experimental for adding extra nodes and edges 
        # if press and event.buttons() == Qt.LeftButton and event.modifiers() == Qt.ShiftModifier: 
        #     # self.handle_modifier_click()
        #     if ui.hover_edge and ui.hover_port: 
        #         self.remove_edge()
        #     elif ui.hover_node: 
        #         self.remove_station()
        
        ##### Handle everything when in drag mode #####
        if self.drag: 
            if self.drag_group: 
                # when a group is selected using the lasso tool, we can drag the group
                self.group_dragging()
            elif ui.drag_label and not self.drag_group: 
                # for single label dragging 
                self.label_dragging()
            elif ui.drag_node and not self.drag_group: 
                # for either individual node dragging or dragging a leg 
                self.node_dragging() 
            else: 
                # when nothing is selected to be dragged we activate the select tool
                self.select_dragging()
        
        # For increasing edge length by port dragging ?????
        # if self.drag and ui.drag_port != None: 
        #     port_pos = ui.hover_node.pos + ui.rose_radius*port_offset[ui.drag_port]
            
        #     dif_port = ui.hover_node.pos - port_pos
        #     dist_port = math.sqrt(dif_port.x()**2 + dif_port.y()**2)

        #     dif_mouse = ui.hover_node.pos - pos
        #     dist_mouse = math.sqrt(dif_mouse.x()**2 + dif_mouse.y()**2)

        #     if dist_mouse > dist_port: 
        #         ui.hover_node.ports[ui.drag_port].min_dist -= 10
        #     elif dist_mouse < dist_port: 
        #         ui.hover_node.ports[ui.drag_port].min_dist += 10
        #     network_change = f'min_dist - changed length of {ui.hover_node}'
                
        ### Did we do anything? Then solve and render as appropriate, and to undo buffer
        if self.network_change is not None:
            self.there_was_change = self.network_change 
            if self.auto_update.isChecked():
                # this is for calculating the new mouse placement after a shift happened while dragging. 
                resolve_shift = layout_lp(self.network, self.label_dist, ui.hover_node)

                if self.group: 
                    self.group.update_group()

                    #### Do we want to move with the button??? 
                    # if self.group and self.pivot_group != None: 
                    #     con_button = self.group.con_buttons_pos[self.pivot_group]
                    #     self.view.translate(self.mouse_pos.x() - con_button.x(), self.mouse_pos.y() - con_button.y())

                # we only translate when we have no dragging, results in more intuitive interaction
                if resolve_shift and not self.drag: 
                    self.view.translate(-resolve_shift.x(), -resolve_shift.y())
                # This is just so the 'drag one node' behaviour works properly again (was removed for some reason)
                elif self.network_change[0:9] == 'drag node' and ui.drag_node and len(ui.drag_node.edges) != 1 and len(self.affected_nodes) <= 2: 
                    self.view.translate(self.mouse_pos.x() - ui.drag_node.pos.x(), self.mouse_pos.y() - ui.drag_node.pos.y())
                if resolve_shift is False:
                    print('no shift')
                    self.error_message = 'Failed to realise layout with current parameters.'
                else: 
                    self.error_message = None
                    if self.auto_render.isChecked():
                        export_loom(self.network,self.filedata)
                        render_loom( "render.json", "render.svg" )
                    if self.show_background.isChecked(): 
                        self.network.set_background_image()

        if release and self.there_was_change:
            self.history_checkpoint( self.there_was_change )
            self.there_was_change = False          

        ### Remember mouse position for next time and redraw.
        self.old_mouse = event.position()
        self.render()  
    
    
    def handle_currently_hovering(self):
        """
        Determines what UI element the mouse is currently hovering over. Including: nodes, labels and ports (and also edges if they are connected)
        It updates: ui.hover_node, ui.hover_label, ui.hover_port (index of port), ui.hover_edge (if it is connected to a port), ui.hover_empty_port (if there is no edge connected to the port)
        """

        # We first reset all variables
        ui.hover_node = None
        ui.hover_label = None
        ui.hover_edge = None
        ui.hover_empty_port = None
        ui.hover_port = None 

        # Find the closest node within a certain radius
        closest_dist = ui.hover_node_radius
        for v in self.network.nodes.values():
            dist = QVector2D(v.pos - self.mouse_pos).length()
            if dist < closest_dist:
                closest_dist = dist
                ui.hover_node = v

        # If a group is hovered 
        if self.group: 
            self.group.has_point_in_label_button(self.mouse_pos)

        # Find the closest label (we do this by checking if the mouse is in the bounding box of the label
        # (old: tried to make this faster by checking if it was close to either the head or tail of the label, this lead to wonky results unfortunatley)
        for v in self.network.nodes.values(): 
            if v.label_node.rectangle_points.containsPoint(self.mouse_pos, Qt.OddEvenFill): 
                ui.hover_label = v.label_node

        # if the mouse is hovering a node we check if we are also hovering a port 
        if ui.hover_node:
            closest_dist = ui.handle_radius

            # We check one of the 8 circular ports
            for i in range(8):
                dist = QVector2D(render.handle_position(ui.hover_node, i) - self.mouse_pos).length()

                if dist < closest_dist:
                    closest_dist = dist
                    ui.hover_port = i

                    # if the port is empty, mark it as available
                    if ui.hover_node.ports[i] is None:
                        ui.hover_edge = None
                        ui.hover_empty_port = i
                    else:
                        # otherwise we select the edge that connects the port
                        ui.hover_edge = ui.hover_node.ports[i]
                        ui.hover_empty_port = None

            # we check one of the 2 rectangular ports that determines if a label is centered 
            # it can only activate as option to choose so that's why we check if there is already a selected node
            # and if the selected edge is a label, only then this particular situation can happen. 
            if (ui.selected_node is not None and type(ui.selected_edge) == Label):
                for i in range(2):
                    vec_to_label_center = (render.handle_center_rose_position(ui.hover_node, i + 8) - self.mouse_pos)

                    # rectangular handling 
                    dist_to_center = max(abs(vec_to_label_center.x() / 2), abs(vec_to_label_center.y()))

                    if dist_to_center < ui.handle_radius:
                        # "port 8 and 9" are the rectangular ports 
                        ui.hover_empty_port = i + 8

            # mark the closest free edge ??
            for e in ui.hover_node.edges:
                if e.free_at(ui.hover_node):
                    dist = QVector2D(render.free_edge_handle_position(ui.hover_node, e) - self.mouse_pos).length()

                    if dist < closest_dist:
                        closest_dist = dist
                        ui.hover_edge = e
                        ui.hover_empty_port = None

    def handle_pan(self, event): 
        if self.is_trackpad_event(event): 
            drag = (self.mouse_pos - self.old_mouse) / self.view.m11() # account for view scale
        else: 
            drag = (self.event_pos - self.old_mouse) / self.view.m11()
        self.view.translate( drag.x(), drag.y() )

    def is_trackpad_event(self, event) -> bool:
        device = event.pointingDevice()
        return device.type() == QPointingDevice.DeviceType.TouchPad

    def handle_menu_edge(self):
        """
        This menu is shown when the user right-clicks a port with connected edge. Depending
        on the edge state, it contains the following actions
        - Straightening the edge
        - Evicting the edge from the hovered node
        - Increasing or decreasing the minimum distance of the edge
        """
        # only allow these options for edges that are connected at the hovered node or are labels
        if type(ui.hover_edge) == Label or ui.hover_edge.free_at(ui.hover_node): return None

        # create empty context menu
        menu = QMenu(self)

        ### ADD Actions 
        straighten = menu.addAction("Straighten") # straighten node 
        menu.addSeparator()

        evict = menu.addAction("Evict") # disconnect/evict the edge from the hovered node
        menu.addSeparator()

        decrease_dist = None
        if ui.hover_edge.min_dist > 100:
            # only allow decreasing if the minimum distance is above 100
            decrease_dist = menu.addAction("Decrease min dist") # decrease the minimum distance
        increase_dist = menu.addAction("Increase min dist") # increase the minimum distance

        # show the menu at the current mouse position and wait for a selection
        action = menu.exec(self.mapToGlobal(self.event_pos.toPoint()))

        # evict the edge from the node
        if action == evict:
            assert ui.hover_node is not None
            assert ui.hover_edge is not None
            ui.hover_node.try_evict(ui.hover_edge)
            self.network_change = f'Evict at "{ui.hover_node.label}" toward "{ui.hover_edge.other(ui.hover_node.name).label}"'

        # straighten all edges from this node 
        if action == straighten:
            assert ui.hover_node is not None
            assert ui.hover_edge is not None
            ui.hover_node.straighten_deg2(ui.hover_edge)
            self.network_change = f'Straighten from "{ui.hover_node.label}" toward "{ui.hover_edge.other(ui.hover_node).label}" (context menu)'

        # Increase the minimum distance of the edge
        if action == increase_dist:
            ui.hover_edge.min_dist += 50
            self.network_change = f'Added distance between "{ui.hover_node.label}" toward "{ui.hover_edge.other(ui.hover_node).label}" (context menu)'

        # Decrease the minimum distance of the edge
        if action == decrease_dist:
            ui.hover_edge.min_dist -= 50
            self.network_change = f'Added distance between "{ui.hover_node.label}" toward "{ui.hover_edge.other(ui.hover_node).label}" (context menu)'


    def handle_menu_node(self):
        """
        This menu is shown when the user right-clicks a node. Depending
        on the edge state, it contains the following actions: 
        - Locking or unlocking the nodes port assignment
        - Smoothening a right-angle node
        - Centering the nodes label
        """
        # create empty context menu
        menu = QMenu(self)
        lock_action, unlock_action, smoothen = None, None, None

        # show either "Lock node" or "Unlock node" depending on current state
        if ui.hover_node.locked:
            unlock_action = menu.addAction("Unlock node")
        else:
            lock_action = menu.addAction("Lock node")
        menu.addSeparator()

        # only have smoothening if the node is currently a right-angle node
        if ui.hover_node.is_right_angle():
            smoothen = menu.addAction("Smoothen")
        menu.addSeparator()

        # always allow the user to center the node label
        center_label = menu.addAction("Center label")

        # show the menu at the current mouse position and wait for a selection
        action = menu.exec(self.mapToGlobal(self.event_pos.toPoint()))

        # center the label on the hovered node
        if action == center_label:
            ui.hover_node.label_node.center_label = True
            self.network_change = f'Centered label at {ui.hover_node.label}'

        # Smoothen the node
        if action == smoothen:
            ui.hover_node.smoothen()
            self.network_change = f'Smoothen "{ui.hover_node.label}"'

        # Lock the node's port assignment
        if action == lock_action:
            ui.hover_node.lock()
            self.network_change = f'Locked {ui.hover_node.label}'

        # Unlock the node's port assignment
        if action == unlock_action:
            ui.hover_node.unlock()
            self.network_change = f'Unlocked {ui.hover_node.label}'

    def handle_single_left_click(self): 
        """
        Handles a single left click. 
        Does the following: 
        - Handles which node should be selected based on the current state of ui.selected_node
        - Turns on drag mode and resets all drag variables 
        - Either resets or activates lasso select 
        """
        #### Handle clicks on nodes and ports
        if ui.selected_node is None:
            # Nothing is currently selected: select whatever is under the cursor
            ui.selected_node = ui.hover_node
            ui.selected_edge = ui.hover_edge
        else:
            if ui.hover_node is None or (ui.hover_edge is None and ui.hover_empty_port is None):
                # Clicked on empty space (no node, no edge, no port), just clear selection
                ui.selected_node = None
                ui.selected_edge = None

            elif ui.hover_node != ui.selected_node:
                # Clicked on a different node, switch selection to that node
                ui.selected_node = ui.hover_node
                ui.selected_edge = ui.hover_edge
            # Otherwise: clicked on the already selected nodes so keep current selection

        #### Handle clicks on label
        # If no label node is currently selected, check if the user is hovering over the label port
        if (ui.selected_label_node is None and ui.hover_node and ui.hover_node.label_node.port == ui.hover_empty_port):
            ui.selected_label_node = ui.hover_node

        #### Handle dragging 

        # Put drag mode on
        self.drag = True 
        ui.drag_node = ui.hover_node
        ui.drag_label = ui.hover_label
        ui.drag_port = ui.hover_port

        # if len(self.lasso_path.toList()) >= 3 and self.lasso_path.containsPoint(self.mouse_pos, Qt.OddEvenFill): 
        #     self.drag_group = True 

        self.drag_group = True 
        # Handle dragging of a lasso group 
        if self.group and self.group.has_point_in_center(self.mouse_pos): 
            # Dragging of move button within a group 
            self.move_group = True 
        elif self.group and self.group.has_point_in_pivot_button(self.mouse_pos) != None: 
            # returns the index of the button to pivot around 
            self.pivot_group = self.group.has_point_in_pivot_button(self.mouse_pos) 
        elif self.group and self.group.has_point_in_expand(self.mouse_pos): 
            self.expand_group = True
        elif self.group and self.group.has_point_in_lock(self.mouse_pos): 
            self.lock_group = True 
        elif self.group and self.group.has_point_in_shape(self.mouse_pos): 
            self.shape_group = True 
        elif self.group and self.group.has_point_in_label_button(self.mouse_pos) != None: 
            self.label_group = True 
        else: 
            # Otherwise deselect everyting 
            self.move_group = False 
            self.expand_group = False
            self.pivot_group = None 
            self.drag_group = False 
            self.group = None 
            self.selection_path = QPolygonF()
            self.brush = QPainterPath()


    def handle_release(self, event):
        """
        Handles mouse release events after a click interaction.
        It does the following things: 
        - Deselects when releasing on empty space
        - Keeps selection if nothing changed
        - Reassigns edges or labels when clicked on a different free port
        - When shift is held it reassigns asymmetric

        self.network_change is updated to describe modifications made.
        """

        # We don't care about dragging only for releasing so we handle locking here 
        if self.group and self.lock_group: 
            locked = self.group.toggle_lock()
            self.network_change = 'unlocked group' if locked else 'locked group'
        if self.group and self.shape_group: 
            success = self.group.create_shape()
            if success: self.network_change = 'changed shape'

        if self.group and self.label_group and self.group.hover_label_port != None: 

            ##### Voor als er in het midden word geklikt 
            if self.group.hover_label_port == 8: 
                pa.post_fix_overlap_ilp_group(self.network, self.label_dist, self.group)
                self.group.label_port_active = None
                self.network_change = f're-assigned group labels via ILP'
            else: 
                new_port = self.group.set_group_labels()
                self.network_change = f'changed labels to port {new_port}'

        # Handles every drag release event 
        self.handle_release_drag(event)

        # If no edge is selected we do nothing 
        if ui.selected_edge is None: return 

        if ui.hover_edge is None and ui.hover_empty_port is None:
            # Released on empty space -> clear selection
            ui.selected_node = None
            ui.selected_edge = None
        elif ui.selected_edge==ui.hover_edge:
            # Released on the same edge -> keep selection unchanged
            pass # leave it selected?
        else:
            # clicked on a new location then previously chosen or clicked something else
            if ui.hover_node==ui.selected_node and ui.hover_empty_port is not None:
                #### label reassignment
                if type(ui.selected_edge) == Label: 
                    # Handle label reassignment to a different port
                    if ui.hover_empty_port >= 8: 
                        # for horizontal centered label positions
                        ui.selected_node.assign_label(2 if ui.hover_empty_port == 8 else 6, hor=True)
                        ui.selected_node.label_node.center_label = True 
                    else: 
                        # Standard label port reassignment
                        ui.selected_node.assign_label(ui.hover_empty_port)
                    self.network_change = f'Reassign at "{ui.selected_node.label}" - label to port {ui.hover_empty_port}'
                #### edge reassignment 
                else: 
                    # If Shift is held -> assign only one end (asymmetric)
                    if event.modifiers() & Qt.ShiftModifier:
                        ui.selected_node.assign(ui.selected_edge, ui.hover_empty_port, force=True)
                    else:
                        # Otherwise -> assign both ends (symmetric reassignment)
                        ui.selected_node.assign_both_ends(ui.selected_edge, ui.hover_empty_port, force=True)

                    self.network_change = f'Reassign at "{ui.selected_node.label}" - "{ui.selected_edge.other(ui.hover_node).label}" to port {ui.hover_empty_port}'

                # we are done so clear selection
                ui.selected_node = None
                ui.selected_edge = None

    def handle_release_drag(self, event):
        """
        Handles mouse release after a drag operation. It: 
        - Clear the current drag state
        - End group dragging
        - Toggle the locked state of nodes inside a lasso when Shift is held
        - Build a node group from nodes inside the lasso to be used when moving the group
        - Track one external connection from the selected group to a node outside it
        """
        # Reset drag state
        self.affected_nodes = []
        self.drag = False
        ui.drag_node, ui.drag_label, ui.drag_port = None, None, None

        # disable the buttons but keep the group 
        if self.drag_group:
            self.move_group = False 
            self.expand_group = False 
            self.lock_group = False 
            self.shape_group = False 
            self.label_group = False 
            self.pivot_group = None 
            return 
            # self.group = None 
            # self.drag_group = False
            # self.move_group = False 
            # self.expand_group = False 
            # self.pivot_group = None 
            # self.selection_path = QPolygonF()
            # self.brush = QPainterPath()

        # ignore lasso logic unless the lasso forms a valid polygon or if we end over a node (because this messes with other actions)
        if len(self.selection_path.toList()) < 2:
            return

        # Shift + lasso: toggle lock state for all nodes inside the lasso
        if event.modifiers() == Qt.ShiftModifier:
            for v in self.network.nodes.values():
                if self.selection_path.containsPoint(v.pos, Qt.OddEvenFill):
                    v.locked = not v.locked

            self.network_change = "Lasso lock/unlock"
            self.selection_path = QPolygonF()
            return

        # Different bahaviour for different selection modes 
        nodes_in_selection: list[Node] = []
        outsider_edges: list[Edge] = []
        outsider_nodes: list[Node] = []
        
        if self.selection_mode == 0: 
            # rectangle selection: collect all nodes inside the rectangle 
            all_points = self.selection_path.toList()
            rect = QRectF(all_points[0], all_points[-1])

            for v in self.network.nodes.values():
                if rect.contains(v.pos):
                    nodes_in_selection.append(v) 

        elif self.selection_mode == 1: 
            # lasso: collect all nodes inside the lasso into a group
            for v in self.network.nodes.values():
                if self.selection_path.containsPoint(v.pos, Qt.OddEvenFill):
                    nodes_in_selection.append(v) 

        elif self.selection_mode == 2: 
            # brush mode: collect all nodes inside the brush 
            path = QPainterPath()

            radius = 40
            for point in self.selection_path.toList():
                circle = QPainterPath()
                circle.addEllipse(point, radius, radius)
                path = path.united(circle)

            path = path.simplified()
            brush = path.toFillPolygon()
            
            for v in self.network.nodes.values():
                if brush.containsPoint(v.pos, Qt.OddEvenFill):
                    nodes_in_selection.append(v)
            
        # If no nodes are found in the lasso we do not proceed 
        if len(nodes_in_selection) < 1: return 

        # Create a group 
        self.group = Group(nodes_in_selection)

    def handle_double_click(self): 
        """
        Handles a double-click interaction on an edge 
        - The edge connected to the currently hovered node is straightened. 

        self.network_change is updated to describe modifications made.
        """
        # if no edge is hovered over nothing can be straightened
        if ui.hover_edge is None or type(ui.hover_edge) == Label: return 

        # Straighten the hovered edge relative to the hovered node
        ui.hover_node.straighten_deg2( ui.hover_edge )
        self.network_change = f'Straighten from "{ui.hover_node.label}" toward "{ui.hover_edge.other(ui.hover_node).label}" (double click)'

    ### EXPERIMENTAL ####
    def handle_modifier_click(self):
        if ui.edge_from and ui.edge_from != ui.hover_node: 
            stations = [
                "Oakridge", "Northgate", "Rivermoor", "Eastfield", "Brookside", "Hilltop",
                "Westend", "Pinewood", "Lakeside", "Stonebridge", "Alderbay", "Redford",
                "Glenpark", "Highmoor"
            ]
            station = stations[self.station_added]
            self.network.nodes[station] = Node(self.mouse_pos.x(), self.mouse_pos.y(), station, station)
            self.station_added += 1
            edge = add_edge(ui.edge_from, self.network.nodes[station])
            self.network.edges.append(edge)
            self.network_change = 'added node and edge'
            ui.edge_from = self.network.nodes[station] 
            ui.hover_node = None 

        if ui.hover_node: 
            ui.edge_from = ui.hover_node 

    def remove_station(self): 
        node = ui.hover_node 

        if len(node.edges) == 2: 
            to_remove = node.edges[0]
            to_keep = node.edges[1]

            neighbour = to_remove.other(node)
            port = to_remove.port_at(neighbour)
            neighbour.ports[port] = to_keep 
            neighbour.edges.remove(to_remove)
            neighbour.edges.append(to_keep)
            self.network.edges.remove(to_remove)

            id = to_keep.id(node)
            to_keep.v[id] = neighbour
            to_keep.port[id] = port

        else: 
            for edge in node.edges: 
                neighbour = edge.other(node)
                port = edge.port_at(neighbour)
                neighbour.ports[port] = None 
                neighbour.edges.remove(edge)
                self.network.edges.remove(edge)

        for line in self.network.deg_2_lines: 
            if node.name in line: 
                line.remove(node.name)
                if len(line) == 0: 
                    self.network.deg_2_lines.remove(line)
        del self.network.nodes[node.name]
        ui.hover_node = None

    def remove_edge(self): 
        edge = ui.hover_edge
        port = ui.hover_port
        for node in edge.v: 
            node.ports[port] = None 
            node.edges.remove(edge)
        self.network.edges.remove(edge)
        
    
    def node_dragging(self):
        """
        Handles dragging of a node and also does this for the rest of the line 

        The function does the following: 
        - Computes how far the drag extends along connected edges (depth) - at the moment it does it only for a single node in the depth to make it less funky. (could be changed to do it for the whole chain)
        - Locks affected nodes along the path
        - Reassigns edge ports on neighbouring nodes based on proximity
        - stops when reaching nodes that are not degree-2
        """
        gen_depth = None
        self.affected_nodes = []

        for edge in ui.drag_node.edges:
            current_edge = edge
            current_node = ui.drag_node

            # compute distance from dragged node to mouse 
            dif = ui.drag_node.pos - self.mouse_pos
            dist = math.sqrt(dif.x()**2 + dif.y()**2)

            # determine how deep the effect propagates along the edge
            depth = int(2 * dist / current_edge.min_dist) 
            gen_depth = depth

            # depth at which reassignment should occur (so it only happens once instead of for all nodes)
            affect_depth = depth - 1

            # traverse along the edge up to the computed depth
            for i in range(depth):
                self.affected_nodes.append(current_node)
                current_node.lock()

                # move to the neighbour allong the current edge
                neighbour = current_edge.other(current_node)
                # determine if there is a better port to assign to 
                closer_port = neighbour.check_for_closer_port(self.mouse_pos)

                # if neighbour is not deg-2, limit how far the bend goes (ensures something still happens even for short legs)
                if len(neighbour.edges) != 2:
                    affect_depth = i

                # reassign edge if we are at the correct depth for reassignment
                if closer_port != current_edge.port_at(neighbour) and i == affect_depth:
                    neighbour.assign_both_ends(current_edge, closer_port)
                    current_port = current_edge.port_at(neighbour)
                    self.network_change = (f'drag node - Reassign at "{current_node.label}" - "{neighbour.label}" from port {current_port} to {closer_port}')

                current_node = neighbour
                # stop traversal if node is not deg 2
                if len(current_node.edges) != 2:
                    break

                # continue with the next edge 
                current_edge = (current_node.edges[1] if current_edge == current_node.edges[0] else current_node.edges[0])

    def label_dragging(self): 
        """
        Handles dragging of a label across a node.
        It checks whether there is a closer available port to attach the label to. 
        If a closer and free port is found, the label is reassigned to that port.
        """

        # determine the closest valid port to the current mouse position
        closer_port = ui.drag_label.node.check_for_closer_port(self.mouse_pos)

        # closest port is different from the current one and is free, reassign
        if closer_port != ui.drag_label.port and ui.drag_label.node.isfree(closer_port):
            ui.drag_label.node.assign_label(closer_port)

            self.network_change = (f'drag label - Reassign label at {ui.drag_label.label_text} from {ui.drag_label.port} to {closer_port}')

    def group_dragging(self): 
        """
        Handles dragging of the lasso selected group around an external pivot edge.

        If the external node's closed port has changed relative to the mouse we rotate either clocwise or counter clockwise by: 
        - Locking all nodes in the group
        - Reassigning internal group edges to shifted ports
        - Reassigning each node's label port
        """

        # if the group can not be moved we do nothing 
        if not self.group.can_be_moved(): return 

        if self.move_group: 
            moved = self.group.move(self.mouse_pos)
            if moved: self.network_change = 'moved group' 
        elif self.pivot_group != None: 
            pivot_point, rotation = self.group.pivot(self.mouse_pos, self.pivot_group)
        
            if pivot_point: 
                self.network_change = 'pivot clockwise' if rotation <= 0 else 'pivot counter clockwise'
        elif self.expand_group: 
            self.group.expand(self.mouse_pos)
            self.network_change = 'increase length'

    def select_dragging(self): 
        self.selection_path.append(self.mouse_pos) 
        # brush mode 
        if self.selection_mode == 2: 
            circle = QPainterPath()
            circle.addEllipse(self.mouse_pos, 50, 50)
            self.brush = self.brush.united(circle)
            self.brush = self.brush.simplified()

    def handle_group_select(self, id: str | None): 

        # First clear the original group, if there is one
        self.move_group = False 
        self.expand_group = False
        self.pivot_group = None 
        self.drag_group = False 
        self.shape_group = False
        self.lock_group = False 
        self.group = None 
        self.selection_path = QPolygonF()
        self.brush = QPainterPath()

        if id == None: return 

        # then update the group 
        self.group = self.groups[id]
        self.group.update_group()
    
    def handle_scale_at(self, mouse_pos, scale):
        pos = self.worldspace(mouse_pos)
        scaleAt = QTransform( scale,0, 0,scale, (1-scale)*pos.x(), (1-scale)*pos.y() )
        self.view = scaleAt * self.view

    def wheelEvent(self, event):
        if event.pixelDelta().manhattanLength() > 0 and event.source()==Qt.MouseEventSource.MouseEventSynthesizedBySystem:
            # Actually touchpad pan or 2D scroll
            if event.modifiers() & Qt.AltModifier:
                # Hold alt to zoom anyway
                s = pow( 1.2, event.angleDelta().y()/120 )
                self.handle_scale_at(event.position(), s)
            else:
                # Actually pan
                drag = event.pixelDelta() / self.view.m11() # m11 accounts for view scale
                self.view.translate( drag.x(), drag.y() )
        elif event.angleDelta().y() != 0 and event.source()==Qt.MouseEventSource.MouseEventNotSynthesized:
            # Actual mouse wheel zoom
            s = pow( 1.2, event.angleDelta().y()/120 )
            self.handle_scale_at(event.position(), s)
        self.render()

    # Fiddle with some gesture events to make pinch zoom works
    def event(self, event):
        if event.type() == QEvent.Gesture:
            return self.gestureEvent(event)
        return super().event(event)
    def gestureEvent(self, event):
        if pinch := event.gesture(Qt.PinchGesture):
            self.handlePinch(pinch)
        return True
    def handlePinch(self, pinch):
        if pinch.state() == Qt.GestureStarted:
            pass
        elif pinch.state() in (Qt.GestureUpdated, Qt.GestureFinished):
            self.handle_scale_at(pinch.centerPoint(), pinch.scaleFactor())
            self.render()

    def open_dialog(self) -> str:
        file_name, _ = QFileDialog.getOpenFileName(None, 'Open File', '', 'All Files (*)')

        if file_name:
            if file_name[-8:]==".graphml":
                self.network = read_network_from_graphml(file_name)
                self.filedata = None
                self.filename = file_name[:-8]
            elif file_name[-5:] == ".json": 
                self.network, self.filedata = read_network_from_loom(file_name)
                self.filename = file_name[:-5]
            elif file_name[-6:] == '.newey':
                self.network = read_newey_file(file_name)
                self.filename = file_name[:-6]
            else: 
                print('File format not supported!')
                return 
            
            self.network.scale_by_shortest_edge( min_edge_scale )
            self.network.find_degree_2_lines()
            self.network.calculate_mid_point()
            self.network.find_min_max_geo()
            self.network.divide_in_lines()
            self.zoom_to_network()
            self.render()

        return file_name
        
    def create_image(self):
        scale = 6 # could increase resotion
        src_size = self.size()
        out_size = QSize(src_size.width() * scale, src_size.height() * scale)

        img = QImage(out_size, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)  # 0xFFFFFFFF for white background

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        painter.scale(scale, scale) # creates bigger canvas 

        # scale the view such that everything is zoomed in more
        pos = self.worldspace(QPointF(0,0))
        scaleAt = QTransform( scale,0, 0,scale, (1-scale)*pos.x(), (1-scale)*pos.y() )
        view = scaleAt * self.view

        self._render(painter, view, export=True)       
        painter.end()

        img.save(str(get_unique_filename(self.filename, extension='png')))

    def save_file(self): 
        file_path = write_newey_file(self.network)
        print(f"Saved to {file_path}")
    
    def get_present_state(self) -> tuple: 
        current_network = self.network.clone()
        current_group = [] 
        if self.group: 
            current_group = [(self.group.name, self.group.color, self.group.bend_pentalty, self.group.label_hor, self.group.label_same_side)]
            current_group += [node.name for node in self.group.nodes]
        current_groups = []
        for group_name, group in self.groups.items(): 
            new_group = [(group_name, group.color, group.bend_pentalty, group.label_hor, group.label_same_side)]
            new_group += [node.name for node in group.nodes]
            current_groups.append(new_group)
        
        return (current_network, current_group, current_groups)

    def set_history(self, history): 
        self.network: Network = history[1].clone()
        self.group = None

        selected_group = history[2]
        if selected_group != None and len(selected_group) > 0: 
            nodes = [node for node in self.network.nodes.values() if node.name in selected_group[1:]]
            if len(nodes) > 0: 
                self.group = Group(nodes, selected_group[0][0], selected_group[0][1], bend=selected_group[0][2], hor=selected_group[0][3], same_side=selected_group[0][4])
        
        self.groups = {}
        for group in history[3]: 
            nodes = [node for node in self.network.nodes.values() if node.name in group[1:]]
            if len(nodes) > 0: 
                self.groups[group[0][0]] = Group(nodes, group[0][0], group[0][1],  bend=group[0][2], hor=group[0][3], same_side=group[0][4])
       
            
