from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QLabel, QCheckBox, QMessageBox, QDialog, QSlider, QComboBox, QButtonGroup, QScrollArea, QListWidget, QListWidgetItem, QToolButton, QInputDialog, QApplication
from PySide6.QtGui import Qt, QAction, QKeySequence, QPolygonF, QIcon, QPixmap, QPainter, QColor, QPalette
from PySide6.QtCore import QPointF, QSize, Signal

import datetime
import copy 

from elements.canvas import Canvas
from elements.network import Node, Network
from elements.group import Group 
from elements.bend_dialog import BendPenaltyDialog

import helpers.port_assign as port_assign 
import helpers.layout as layout

from io_management.fileformat_loom import export_loom, render_loom

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Newey")
        self.setMinimumSize(1280, 720)

        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left scrollable menu ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setMinimumWidth(200)
        self.scroll_area.setMaximumWidth(220)

        sidebar = QWidget()
        button_layout = QVBoxLayout()
        sidebar.setFixedWidth(200)

        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setAutoFillBackground(True)
        
        sidebar.setLayout(button_layout)
        self.scroll_area.setWidget(sidebar)

        # --- Right canvas ---
        self.canvas = Canvas(self.history_checkpoint)

        root.addWidget(self.scroll_area)
        root.addWidget(self.canvas) 

        self.methods = ["Rounding", "Matching", "Global"]
        self.method_choice: int = 2
        self.sliders = [[], [], [], []]
        self.slider_values = [[], [], [], []]

        self.selection_modes = [("Rectangle", "square_select.png"), ("Lasso", "lasso_select.svg"), ("Brush", "brush_select.png")]
        self.selection_buttons = {}

        # history buffer
        self.history: list[tuple[str, Network]] = []
        self.history_index = -1

        self.construct_sidebar(button_layout)
        self.construct_menubar()
        button_layout.addStretch()

         # Control variables
        self.label_strength: float = 0.1

        self.do_port_assign()
        self.history_checkpoint( "Initial drawing" )
        self.update_history_actions()
    
    def construct_sidebar(self, layout):
        
        add_group_separator(layout)
        title = QLabel("Newey")
        
        title.setStyleSheet("font-weight: bold; color: #b52b2b; font-size: 54px")
        layout.addWidget(title)

        add_group_separator(layout)
        

        #### SELECTION METHODS 
        # label = QLabel("Selection method")
        # label.setStyleSheet("font-weight: bold;")
        # layout.addWidget(label)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        layout.addLayout(button_row)

        self.hor_buttons = QButtonGroup(self)
        self.hor_buttons.setExclusive(True)

        for i, (mode, path) in enumerate(self.selection_modes):
            button = QPushButton(mode)
            button.setCheckable(True)
            button.setFixedSize(48, 48)
            button.setIcon(QIcon(f'assets/{path}'))
            button.setIconSize(QSize(28, 28))
            button.setText('')
            button.setProperty("mode", mode)
            button.setToolTip(mode)
            # set first button checked 
            if i == 1: button.setChecked(True)

            self.hor_buttons.addButton(button)
            button_row.addWidget(button)

        self.hor_buttons.buttonClicked.connect(self.selection_mode_changed)

        # Color items representing each line 
        self.group_list = GroupList(self.canvas, self.history_checkpoint, select_buttons=self.hor_buttons)
        layout.addWidget(self.group_list)
        add_sidebar_button(layout, "Add Group", self.add_group_selection)
        add_sidebar_button(layout, "Apply globally", lambda: self.go_button_clicked())
        add_sidebar_button(layout, "Fix label overlap", lambda: self.do_fix_label_overlap())

        #### PORT ASSIGNMENT

        # Buttons to control port assignment methods 
        # add_group_separator(layout)
        port_assign_box = CollapsibleBox("Port assignment", open=False)
        layout.addWidget(port_assign_box)
        
        # Dropdown
        self.combo = QComboBox()
        self.combo.addItems(self.methods)
        self.combo.setCurrentIndex(self.method_choice)
        self.combo.currentIndexChanged.connect(self.dropdown_changed)
        port_assign_box.addWidget(self.combo)

        # General sliders 

        # sliders rounding method 

        # sliders matching method
        self.add_slider(port_assign_box, "Label Horizontal Weight", 0, 200, 0, slider_set=2)

        # sliders global method
        self.add_slider(port_assign_box, "Bend penalty", 0, 50, 0, slider_set=3, tick_size=0.1)
        self.add_slider(port_assign_box, "Label Horizontal Weight", 0, 200, 10, slider_set=3)
        self.add_slider(port_assign_box, "Label Same-Side Weight", 0, 100, 10, slider_set=3)

        # Exectue chosen method 
        # add_sidebar_button(layout, "GO!", lambda: self.do_port_assign())
        
        # Auto update port assignment 
        self.auto_update_port = QCheckBox("Auto-update Ports")
        self.auto_update_port.setChecked(True)
        # layout.addWidget(self.auto_update_port)

        # evict port assignment choice 
        # add_sidebar_button(layout, "Evict all", lambda: self.do_assign_reset())


        #### LAYOUT ALGO 

        # Buttons to control the layout algorithm
        # add_group_separator(layout)
        layout_box = CollapsibleBox("Layout", open=False)
        layout.addWidget(layout_box)

        # general slider
        self.add_slider(layout_box, "Min edge length", 0, 150, 100, slider_set=0)
        self.add_slider(layout_box, "Label distance", 0, 50, 25, slider_set=0)

        # add_sidebar_button(layout, "Update layout", lambda: self.do_layout())

        self.canvas.auto_update = QCheckBox("Auto-update")
        self.canvas.auto_update.setChecked(True)
        # layout_box.addWidget(self.canvas.auto_update)
        # add_sidebar_button(layout, "Reset", lambda: self.do_reset_layout())

        # add_sidebar_button(layout_box, "GO!", lambda: self.go_button_clicked())

        ### POST FIX LABELING

        # add_group_separator(layout)
        labels_box = CollapsibleBox("Labels", open=False)
        layout.addWidget(labels_box)

        ### RENDERING  

        # add_group_separator(layout)
        rendering_box = CollapsibleBox("Rendering", open=False)
        layout.addWidget(rendering_box)

        add_sidebar_button(rendering_box, "Render using Loom", lambda: self.do_render())
        self.canvas.auto_render = QCheckBox("Auto-render")
        self.canvas.auto_render.setChecked(False)
        rendering_box.addWidget(self.canvas.auto_render)

        ### VIEW
        # add_group_separator(layout)
        view_box = CollapsibleBox("View", open=False)
        layout.addWidget(view_box)

        add_sidebar_button(view_box, "Zoom to fit", lambda: self.do_zoom_to_fit())
        self.canvas.show_background = QCheckBox("Show Original")
        self.canvas.show_background.setChecked(False)
        self.canvas.show_background.clicked.connect(lambda: self.canvas.render())
        view_box.addWidget(self.canvas.show_background)

        self.dropdown_changed(self.method_choice)

    def go_button_clicked(self): 
        self.do_port_assign()
        self.history_checkpoint('Automatic port assignment')

    def selection_mode_changed(self, button: QPushButton):
        self.group_list.clear_selection()
        button.setChecked(True)
        self.canvas.selection_mode = [mode[0] for mode in self.selection_modes].index(button.property("mode"))
        
    def dropdown_changed(self, index: int):
        # We add one because the first slider set is for general sliders 
        self.method_choice = index + 1

        for slider_set in self.sliders[1:]: 
            for (label, slider) in slider_set: 
                label.hide()
                slider.hide() 

        for (label, slider) in self.sliders[self.method_choice]: 
            label.show()
            slider.show()

    def add_slider(self, layout, text, min, max, value, slider_set, tick_size=1): 
        label = QLabel(text)
        layout.addWidget(label)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(min)
        slider.setMaximum(max)
        slider.setValue(value)
        # slider.setTickPosition(QSlider.TicksBelow)
        # slider.setTickInterval(1)
        # slider.setFixedWidth(200)
        slider_index = len(self.sliders[slider_set])
        slider.valueChanged.connect(lambda x: self.update_slider_value(x, slider_set, slider_index, tick_size))
        slider.sliderReleased.connect(lambda: self.on_slider_release(text, slider_set))

        layout.addWidget(slider)
        
        self.sliders[slider_set].append((label, slider))
        self.slider_values[slider_set].append(value)

    def update_slider_value(self, value: float, slider_set: int, slider: int, tick_size=1):
        self.slider_values[slider_set][slider] = value * tick_size

        # For the label distance, needs to be set in canvas also
        if slider_set==0: 
            if slider==0: 
                for edge in self.canvas.network.edges: 
                    edge.min_dist = value * tick_size
                    edge.lock()
                self.do_layout(global_slide=True)
            if slider==1: 
                self.canvas.label_dist = value * tick_size
                self.do_layout()
        elif slider_set==3: 
            if slider == 0: 
                for node in self.canvas.network.nodes.values(): 
                    node.bend_penalty = value * tick_size
            if slider == 1: 
                for node in self.canvas.network.nodes.values(): 
                    node.label_hor = value * tick_size
            if slider == 2: 
                for node in self.canvas.network.nodes.values(): 
                    node.label_same_side = value * tick_size
            self.do_port_assign()
        elif self.auto_update_port.isChecked(): 
            self.do_port_assign()

    def on_slider_release(self, text: str, slider_set: int): 
        if slider_set == 0: self.history_checkpoint(f"Altered layout by changing {text}")
        else: self.history_checkpoint(f"Altered port assignment by {text}")

    def add_group_selection(self): 
        name, ok = QInputDialog.getText(self, "Enter name", "Name:")
        name = name.strip()
        if ok and name:
            can_add = self.canvas.add_group(name, name, None)
            if can_add: self.group_list.add_entry(name, name, None)
        
    def do_port_assign(self): 
        match self.method_choice: 
            case 1: self.do_assign_round()
            case 2: self.do_assign_matching()
            case 3: self.do_assign_ilp()

    def do_assign_round(self):
        port_assign.assign_by_rounding(self.canvas.network)
        self.update_layout_if_auto()
        self.canvas.render()

    def do_assign_matching(self):
        port_assign.assign_by_local_matching(self.canvas.network)
        self.update_layout_if_auto()
        self.canvas.render()

    def do_assign_ilp(self):
        port_assign.assign_by_ilp(self.canvas.network)
        self.update_layout_if_auto()
        self.canvas.render()

    def do_zoom_to_fit(self):
        self.canvas.zoom_to_network()
        self.canvas.render()

    def do_assign_reset(self):
        self.canvas.network.evict_all_edges()
        self.history_checkpoint("Evict all")
        self.canvas.render()

    def update_layout_if_auto(self):
        if self.canvas.auto_update.isChecked():
            self.do_layout()

    def do_layout(self, global_slide: bool = False):
        if layout.layout_lp(self.canvas.network, label_dist=self.slider_values[0][1], global_slide=global_slide) is False:
            print( "user\t"+"Failed to realize layout.")
            self.canvas.error_message = 'Failed to realise layout with current parameters.'
            # m = QMessageBox()
            # m.setText("Failed to realize layout.")
            # m.setIcon(QMessageBox.Warning)
            # m.setStandardButtons(QMessageBox.Ok)
            # m.exec()
        else: 
            self.canvas.error_message = None
            self.canvas.network.layout_set = True 
            if self.canvas.drawing_is_completely_oob():
                self.canvas.zoom_to_network()
                self.canvas.network.set_background_image()
            self.canvas.render()

    def do_reset_layout(self):
        self.canvas.network.layout_set = False 
        for v in self.canvas.network.nodes.values():
            v.pos = v.geo_pos
        for e in self.canvas.network.edges:
            e.bend = None
        self.canvas.zoom_to_network()
        self.history_checkpoint("Reset layout")
        self.canvas.render()

    def do_fix_label_overlap(self): 
        success = port_assign.post_fix_overlap_ilp_new(self.canvas.network, self.slider_values[0][1])
        if success: 
            self.do_layout()
            self.history_checkpoint("Fix label overlap")
        else: 
            m = QMessageBox()
            m.setText("Failed to realize layout without overlap.")
            m.setIcon(QMessageBox.Warning)
            m.setStandardButtons(QMessageBox.Ok)
            m.exec()

        ##### Brute force solution ######
        # overlaps = self.canvas.network.check_label_overlaps()
        
        # for overlap in overlaps: 
        #     # print(f'{overlap[0].label} with {overlap[1].label}')
        #     found = False 
        #     for v in overlap: 
        #         for p in v.get_free_ports(): 
        #             rect_to_check = v.label_node.get_rectangle_port(p, label_dist=self.slider_values[0][0])
        #             if not self.canvas.network.overlaps_with_label(rect_to_check): 
        #                 v.assign_label(p)
        #                 print(f'Assigned {v.label} to port {p}')
        #                 found = True 
        #                 break 
        #         if found: break 
        

    def do_render(self, tag=None):
        if self.canvas.filedata is None:
            m = QMessageBox()
            m.setText("Cannot render: opened file was not from Loom.")
            m.setIcon(QMessageBox.Warning)
            m.setStandardButtons(QMessageBox.Ok)
            m.exec()
        else:
            export_loom( self.canvas.network, self.canvas.filedata )
            if tag is None: filename = "render.svg"
            else: filename = f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-render-{tag}.svg"
            render_loom( "render.json", filename )

    def construct_menubar(self):
        menu_bar = self.menuBar()
        # File menu
        file_menu = menu_bar.addMenu("File")
        open_action = QAction("Open...", self)
        open_action.setShortcut(QKeySequence('Ctrl+O'))
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)
        save_action = QAction("Save....", self)
        save_action.setShortcut(QKeySequence('Ctrl+S'))
        save_action.triggered.connect(self.canvas.save_file)
        file_menu.addAction(save_action)
        picture_action = QAction("Take picture", self)
        picture_action.setShortcut(QKeySequence('Ctrl+P'))
        picture_action.triggered.connect(self.canvas.create_image)
        file_menu.addAction(picture_action)
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence('Ctrl+Q'))
        file_menu.addAction(exit_action)
        exit_action.triggered.connect(self.close)
        # Edit menu
        edit_menu = menu_bar.addMenu("Edit")
        ## TODO: Fix self.canvas.undo_action ... does not make sense at the moment 
        self.undo_action = QAction("Undo", self)
        edit_menu.addAction(self.undo_action)
        self.undo_action.setShortcut(QKeySequence('Ctrl+Z'))
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("Redo", self)
        edit_menu.addAction(self.redo_action)
        self.redo_action.setShortcut(QKeySequence('Ctrl+Shift+Z'))
        self.redo_action.triggered.connect(self.redo)

    def open_file(self): 
        file_name = self.canvas.open_dialog()

        if file_name: 
            self.group_list.remove_all_items()
            self.group_list.add_current_metro_lines()
            self.group_list.update_height()
            self.history_checkpoint( f'Open "{file_name}"' )
        else: 
            print('Unable to open file')

    def undo(self):
        # Assumes we don't undo to before the start of time
        print("user\t"+"Undo")
        self.history_index -= 1
        self.fetch_history()
        self.update_history_actions()
        self.canvas.render()
    
    def redo(self):
        # Assumes the future exists
        print("user\t"+"Redo")
        self.history_index += 1
        self.fetch_history()
        self.update_history_actions()
        self.canvas.render()
    
    def update_history_actions(self):
        # Set the text and availability of the "undo" menu item based on where we are in time now.
        if self.history_index<1:
            self.undo_action.setEnabled(False)
            self.undo_action.setText("Undo")
        else:
            self.undo_action.setEnabled(True)
            self.undo_action.setText( "Undo " + self.history[self.history_index][0] )

        if self.history_index==len(self.history)-1:
            self.redo_action.setEnabled(False)
            self.redo_action.setText("Redo")
        else:
            self.redo_action.setEnabled(True)
            self.redo_action.setText( "Redo " + self.history[self.history_index+1][0] )
    
    def history_checkpoint(self, text):
        # Log the message
        print( "user\t"+text )
        # Delete the future
        self.history = self.history[0:self.history_index+1]
        
        # Add the present
        current_network, current_group, current_groups = self.canvas.get_present_state()
        current_slider_values = [slider_set[:] for slider_set in self.slider_values]
        current_error = self.canvas.error_message
        self.history.append(( text, current_network, current_group, current_groups, current_slider_values, current_error))
        
        self.history_index += 1
        self.update_history_actions()
    
    def fetch_history(self):
        print(f'fetched - {self.history[self.history_index][0]}')
        self.canvas.set_history(self.history[self.history_index])

        # set sliders
        for set_index, slider_set in enumerate(self.history[self.history_index][4]): 
            for slider, value in enumerate(slider_set):
                self.slider_values[set_index][slider] = value
                self.sliders[set_index][slider][1].setValue(value)
        
        # set group sliders 
        self.group_list.set_groups(self.history[self.history_index][3], self.history[self.history_index][2])

        # set error message 
        self.canvas.error_message = self.history[self.history_index][5]

        if self.history_index == 0: self.canvas.zoom_to_network()

def add_sidebar_button(layout, text, action):
    button = QPushButton(text)
    button.clicked.connect(action)
    layout.addWidget(button)
    return button
        
def add_group_separator(layout):
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    layout.addWidget(line) 
      
class ColorSquare(QWidget):
    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        self.color = color
        self.setFixedSize(16, 16)

    def paintEvent(self, event):
        if not self.color:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.setPen(Qt.black)  # border
        painter.setBrush(QColor(self.color))
        painter.drawRect(rect)

class SliderRow(QWidget):
    value_changed = Signal(int)

    def __init__(self, id, name, group_id, min, max, value, handle_slider_change, handle_slider_release, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.id = id 
        self.group_id = group_id

        self.label = QLabel(name)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min, max)
        self.slider.setValue(value)
        self.value_label = QLabel(str(value))

        self.handle_slider_change = handle_slider_change
        self.handle_slider_relase = handle_slider_release

        self.slider.valueChanged.connect(lambda value: self.handle_value_changed(value))
        self.slider.valueChanged.connect(self.value_changed)
        self.slider.sliderReleased.connect(lambda: self.handle_slider_relase(id))

        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)

    def handle_value_changed(self, value): 
        self.value_label.setText(str(value))
        self.handle_slider_change(self.group_id, self.id, value)


class GroupListItem(QWidget):
    clicked = Signal(object)
    remove_clicked = Signal(object)

    def __init__(self, text, item_id, color, slider_values: tuple, handle_slider_change, handle_slider_release, parent=None):
        super().__init__(parent)
        self.item_id = item_id

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        if color:
            self.icon_widget = ColorSquare(color)
        else:
            self.icon_widget = QWidget()
            self.icon_widget.setFixedWidth(16)

        self.label = QLabel(text)

        self.remove_button = QToolButton()
        self.remove_button.setText("×")
        self.remove_button.setAutoRaise(True)
        self.remove_button.clicked.connect(
            lambda: self.remove_clicked.emit(self.item_id)
        )
        
        top_row.addWidget(self.icon_widget)
        top_row.addWidget(self.label, 1)
        top_row.addStretch()
        top_row.addWidget(self.remove_button)

        outer.addLayout(top_row)

        self.sliders_container = QWidget()
        sliders_layout = QVBoxLayout(self.sliders_container)
        sliders_layout.setContentsMargins(5, 0, 0, 0)
        sliders_layout.setSpacing(2)

        self.slider1 = SliderRow(0, "bend", item_id, 0, 20, slider_values[0], handle_slider_change, handle_slider_release)
        self.slider2 = SliderRow(1, "hor", item_id, 0, 100, slider_values[1], handle_slider_change, handle_slider_release)
        self.slider3 = SliderRow(2, "side", item_id, 0, 200, slider_values[2], handle_slider_change, handle_slider_release)

        sliders_layout.addWidget(self.slider1)
        sliders_layout.addWidget(self.slider2)
        sliders_layout.addWidget(self.slider3)

        outer.addWidget(self.sliders_container)
        self.sliders_container.hide()

        self.current_selected = False
        self.update_style()
        
    
    def set_selected(self, selected):
        self.current_selected = selected
        self.sliders_container.setVisible(selected)
        self.update_style()
        self.adjustSize()

    def update_style(self):

        palette = QApplication.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128

        selected = "#FFFFFF"
        not_selected = "lightgray"

        if not is_dark:
            selected = "black"
            not_selected = "#777777" 

        if self.current_selected:
            self.setStyleSheet(f"""
                QLabel {{
                    color: {selected};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QLabel {{
                    color: {not_selected};
                }}
            """)
    
        # Hacky way to determine whether we click the label/icon or the remove button
    def mousePressEvent(self, event):
        if not self.remove_button.geometry().contains(event.pos()):
            self.clicked.emit(self.item_id)
        super().mousePressEvent(event)


class GroupList(QListWidget):

    def __init__(self, canvas: Canvas, history_checkpoint, select_buttons, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setUniformItemSizes(False)
        self.setFocusPolicy(Qt.NoFocus)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(4)

        self.history_checkpoint = history_checkpoint
        self.canvas = canvas 
        self.select_buttons = select_buttons

        self.items = {}
        self.current_id = None

        self.add_current_metro_lines()

    def add_current_metro_lines(self): 
        # Create the actual groups in the canvas 
        self.canvas.create_groups_from_lines()

        # Add entries to the list 
        for i, color in enumerate(self.canvas.network.lines): 
            self.add_entry(f"Metro Line", color, f"#{color}")

    def add_entry(self, text, item_id, color=None):
        slider_values = self.canvas.groups[item_id].get_slider_values()

        widget = GroupListItem(text, item_id, color, slider_values, self.handle_slider_change, self.handle_slider_release)
        widget.clicked.connect(self.select_item)
        widget.remove_clicked.connect(self.remove_item)

        self.layout.addWidget(widget)
        self.items[item_id] = widget

        self.update_height()

    def select_item(self, item_id):
        # if the selected item is the same we toggle it
        if self.current_id == item_id:
            self.clear_selection()
            return

        # set the previous selected to not selected 
        if self.current_id is not None and self.current_id in self.items:
            self.items[self.current_id].set_selected(False)

        # set current selected to selected 
        self.current_id = item_id
        self.items[item_id].set_selected(True)

        # for the other select type buttons
        self.select_buttons.setExclusive(False)
        for button in self.select_buttons.buttons():
            button.setChecked(False)
        self.select_buttons.setExclusive(True)

        # set group selection mode in the canvas 
        self.canvas.color_selected = item_id
        self.canvas.selection_mode = 3 

        self.canvas.handle_group_select(item_id)
        self.canvas.render()
        self.update_height()

    def clear_selection(self):
        # when we don't want any of the items to be selected 
        if self.current_id is not None and self.current_id in self.items:
            self.items[self.current_id].set_selected(False)
        self.current_id = None
        self.canvas.handle_group_select(None)
        self.update_height()

    def set_groups(self, groups, selected_group): 
        self.remove_all_items() 
        for i, group in enumerate(groups): 
            name = group[0][0]
            color = group[0][1]
            if color: 
                self.add_entry("Metro Line", name, color)
            else: 
                self.add_entry(name, name, color)
        if selected_group: 
            if selected_group[0][0] in self.items: 
                self.select_item(selected_group[0][0])

    def remove_item(self, item_id):
        # remove the item from the list 
        widget = self.items.pop(item_id, None)
        if not widget: return

        if self.current_id == item_id:
            self.current_id = None
        
        # remove the item from the layout
        self.layout.removeWidget(widget)
        widget.deleteLater()
        
        # Also remove the group from the canvas 
        self.canvas.groups.pop(item_id)
        self.update_height()

    def remove_all_items(self): 
        for item in self.items: 
            widget = self.items[item]
            self.layout.removeWidget(widget)
            widget.deleteLater()
        self.items = {}
        # self.clear_selection()
    
    def handle_slider_change(self, item_id, slider_id, value): 
        if not self.canvas.group: 
            self.current_id = item_id
            self.items[item_id].set_selected(True)
            self.canvas.handle_group_select(item_id)

        match slider_id: 
            case 0: self.canvas.groups[item_id].update_bend_penalty(value) 
            case 1: self.canvas.groups[item_id].update_hor_label(value) 
            case 2: self.canvas.groups[item_id].update_same_side_label(value) 
            
        port_assign.assign_by_ilp(self.canvas.network)
        layout.layout_lp(self.canvas.network)

        self.canvas.groups[item_id].update_group()
        self.canvas.render()
    
    def handle_slider_release(self, id): 
        if self.canvas.group: 
            # needed such that we update the showing of labels also when we just release a slider
            self.canvas.group.show_labels = False
            if id == 0: text = "bend-penalty"
            elif id == 1: text = "label horizontal weight"
            elif id == 2: text = "same side weight"
            else: text = ''
            self.history_checkpoint(f"Port assignement by changing local {text}")
            self.canvas.render()
    
    def update_height(self):
        # Updates the height of the fixed height of the list 
        total = self.layout.contentsMargins().top() + self.layout.contentsMargins().bottom()

        for i in range(self.layout.count()):
            item = self.layout.itemAt(i)
            if item.widget():
                w = item.widget()
                w.adjustSize()
                total += w.sizeHint().height()

        total += (self.layout.count() - 1) * self.layout.spacing()
        self.setFixedHeight(total)

class CollapsibleBox(QWidget):
    def __init__(self, title="", open=True, parent=None):
        super().__init__(parent)

        ### Header
        self.toggle_button = QToolButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(open)
        self.toggle_button.setArrowType(Qt.DownArrow)
        self.toggle_button.setFixedSize(12, 12)
        self.toggle_button.clicked.connect(self.on_toggled)
        self.toggle_button.setStyleSheet("""
            QToolButton {
                border: none;
                background: transparent;
            }
        """)

        self.title_label = QLabel(title)

        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(5, 5, 5, 0)

        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.header.mousePressEvent = self.header_clicked

        ### Line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setContentsMargins(0, 0, 0, 0)

        ### Content
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(5, 0, 5, 5)

        ### Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.header) 
        main_layout.addWidget(line)
        main_layout.addWidget(self.content)

        palette = QApplication.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128

        bg = "#212121" if is_dark else "#FFFFFF"

        self.setObjectName("collapsibleBox")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QWidget#collapsibleBox {{
                background-color: {bg};
            }}
        """)

        self.on_toggled(open)

    def header_clicked(self, event):
        self.toggle_button.toggle()
        self.on_toggled(self.toggle_button.isChecked())

    def on_toggled(self, checked):
        self.content.setVisible(checked)
        self.toggle_button.setArrowType(
            Qt.DownArrow if checked else Qt.RightArrow
        )

    def addWidget(self, widget):
        self.content_layout.addWidget(widget)

    def addLayout(self, layout):
        self.content_layout.addLayout(layout)
