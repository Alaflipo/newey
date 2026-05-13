from PySide6.QtGui import QColor, QPainterPath, QPen, QFont, QPainter, QPolygonF, QBrush, QTransform
from PySide6.QtCore import Qt, QRectF
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtSvg import QSvgRenderer

from math import cos, sin, pi
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QFontMetricsF, QPen, QBrush, QColor

from elements.network import *
from elements.group import Group
from math import sqrt, hypot

import ui

diag = 1/sqrt(2) # notational convenience

rotation_factor = [0, -45, -90, 45, 0, -45, -90, 45]

def opposite_port( p ):
    return (p+4)%8

port_offset = [ QPointF(-1,0)
              , QPointF(-diag,diag)
              , QPointF(0,1)
              , QPointF(diag,diag)
              , QPointF(1,0)
              , QPointF(diag,-diag)
              , QPointF(0,-1)
              , QPointF(-diag,-diag)
              ]

font = QFont("Helvetica", 30, QFont.Bold)

def render_network( painter: QPainter, net: Network, show_background: bool, label_dist: int, group: Group, export: bool ):

    # Coordinate system axes
    painter.setPen(QPen(QColor('lightgray'),10))
    painter.setFont(font)
    # painter.drawLine( 0, 0, 100, 0 )
    # painter.drawText( 130, 10, "x" )
    # painter.drawLine( 0, 0, 0, 100 )
    # painter.drawText( 1, 150, "y" )

    # Render background 
    if show_background: 
        for e in net.edges: 
            color = QColor('#'+e.color[0])
            color.setAlpha(20) 
            ui.edge_pen.setColor(color)
            painter.setPen( ui.edge_pen )
            painter.setBrush(Qt.NoBrush )

            painter.drawLine(e.v[0].background_pos, e.v[1].background_pos)

        for _, v in net.nodes.items(): 
            painter.setPen(ui.node_pen_background)
            painter.setBrush(ui.node_brush)
            painter.drawEllipse(v.background_pos, 10, 10)

    ### Rendering of connecting lines 
    ### We render bezier curves, when there are multple lines represented as one edge we render each line with a little bit of offset
    painter.setBrush(Qt.NoBrush )
    for e in net.edges:
        # distance between each line with stroke set at 2
        line_spacing = 4 
        for i in range(len(e.color)):
            ui.edge_pen.setColor(QColor('#' + e.color[i]))
            # if e.locked: 
            #     painter.setPen(ui.lock_pen)
            # else: 
            painter.setPen(ui.edge_pen)

            # calculate the offset for each parallel colored line
            offset_amount = (i - (len(e.color) - 1) / 2) * line_spacing
            offset = parallel_line_offset(e.v[0].pos, e.v[1].pos, offset_amount)

            # we add the offset to each calculation 
            a_start = e.v[0].pos + offset
            if e.free_at(e.v[0]):
                if e.v[0] == ui.hover_node:
                    a_1 = free_edge_handle_position(e.v[0], e) + offset
                else:
                    a_1 = e.v[0].pos + (ui.bezier_radius * e.direction(e.v[0])).toPointF() + offset
                a_2 = e.v[0].pos + (ui.bezier_cp * e.direction(e.v[0])).toPointF() + offset
            else:
                a_1 = e.v[0].pos + ui.bezier_radius * port_offset[e.port[0]] + offset
                a_2 = e.v[0].pos + ui.bezier_cp * port_offset[e.port[0]] + offset

            b_start = e.v[1].pos + offset
            if e.free_at(e.v[1]):
                if e.v[1] == ui.hover_node:
                    b_1 = free_edge_handle_position(e.v[1], e) + offset
                else:
                    b_1 = e.v[1].pos + (ui.bezier_radius * e.direction(e.v[1])).toPointF() + offset
                b_2 = e.v[1].pos + (ui.bezier_cp * e.direction(e.v[1])).toPointF() + offset
            else:
                b_1 = e.v[1].pos + ui.bezier_radius * port_offset[e.port[1]] + offset
                b_2 = e.v[1].pos + ui.bezier_cp * port_offset[e.port[1]] + offset

            bend = None if e.bend is None else e.bend + offset

            path = QPainterPath()

            if e.free_at(e.v[0]):
                path.moveTo(a_1)
            else:
                path.moveTo(a_start)
                path.lineTo(a_1)

            if bend is None:
                path.cubicTo(a_2, b_2, b_1)
            else:
                path.lineTo(bend)
                path.lineTo(b_1)

            if not e.free_at(e.v[1]):
                path.lineTo(b_start)

            painter.drawPath(path)


    # For indicator lines of minimal edge length (should be done earlier because that looks prettier)
    if ui.hover_node and net.layout_set: 
        for e in ui.hover_node.edges:  
            # For minimal length indicator
            if (e.length() >= e.min_dist): 
                if not e.bend: 
                    draw_indicator_lines(painter, QLineF(ui.hover_node.pos, e.other(ui.hover_node).pos), e.min_dist)
                else: 
                    first_part = QLineF(ui.hover_node.pos, e.bend)
                    draw_indicator_lines(painter, first_part, e.min_dist)
                    left_over = (first_part.length() % e.min_dist)
                    second_part = QLineF(e.bend, e.other(ui.hover_node).pos)
                    draw_indicator_lines(painter, second_part, e.min_dist, start=-1 * left_over)
            
            if e.locked: 
                draw_locked_symbol(painter, ui.hover_node.pos, e.other(ui.hover_node).pos, e.length()/2)

    # Draw the nodes
    painter.setPen(ui.node_pen)
    painter.setBrush(ui.node_brush)
    for name, v in net.nodes.items():
        
        if v.locked and not export: 
            painter.setPen(ui.lock_pen)
        else: 
            painter.setPen(ui.node_pen)
        
        painter.setBrush(ui.node_brush)
        painter.drawEllipse(v.pos, 10, 10)

        # We don't render labels if there is no text to be rendered 
        if v.label_node.label_text == "": continue 

        # We don't render labels if a node is being dragged (we do want to render when labels are dragged)
        if ui.drag_node and not ui.hover_node and not ui.drag_label: continue 

        # We don't render labels if certain buttons in the group are clicked or in use
        if group and v in group.nodes and not group.show_labels and group.hover_label_port == None: continue 

        # Now we can draw the label
        painter.setBrush(QBrush(QColor("lightgray")))
        painter.setFont(QFont("Arial", 15))
        draw_label(painter, v.pos, v.label_node.port, v.label, label_dist, v.label_node.center_label)
    
    # Draw UI for the node close to the mouse
    if ui.hover_node:
        draw_rose( painter, ui.hover_node )
        for e in ui.hover_node.edges:
            if e.free_at(ui.hover_node):
                painter.setPen( ui.rose_used_pen)
                painter.setBrush( ui.rose_used_brush )
                if e==ui.selected_edge: painter.setBrush( ui.selected_brush )
                if e==ui.hover_edge: painter.setBrush( ui.highlight_brush )
                handle_pos = free_edge_handle_position(ui.hover_node, e)
                painter.drawEllipse(handle_pos,ui.handle_radius,ui.handle_radius)

def parallel_line_offset(p1: QPointF, p2: QPointF, amount: float) -> QPointF:
    line = QLineF(p1, p2)
    line_length = line.length()

    if line_length == 0:
        return QPointF(0, 0)

    return QPointF(-line.dy() / line_length * amount, line.dx() / line_length * amount)

def draw_label(painter: QPainter, node_pos: QPointF, port: int, text: str, label_dist: float, horizontal: bool): 

    padding = 3
    if port != None: 
        angle = rotation_factor[port]
    else: 
        # If there was no port assigned for the label we just render it as if assigned to the right most port
        angle = rotation_factor[4]

    fm = QFontMetricsF(painter.font())
    text_rect = fm.boundingRect(text)

    w = text_rect.width() + 2 * padding
    h = text_rect.height() + 2 * padding

    # we should calcualte the rectangle differently depending on the port side
    south_west_side = port in (0, 1, 2, 7)

    # for horizontal labels on ports 2 and 6 (verticals)
    if horizontal and port in (2, 6):
        angle = 0
        if port == 6:  
            rect = QRectF(-w / 2, -label_dist - h, w, h)
        else:          
            rect = QRectF(-w / 2, label_dist, w, h)
    else: 
        if south_west_side:
            rect = QRectF(-label_dist - w, -h / 2, w, h)
        else:
            rect = QRectF(label_dist, -h / 2, w, h)

    rect_with_padding = rect.adjusted(padding, padding, -padding, -padding)

    painter.save()
    painter.translate(node_pos)
    painter.rotate(angle)

    # draw the bounding rectangle 
    painter.setPen(QPen(QColor("lightgray")))
    painter.drawRoundedRect(rect, 4, 4)

    # draw the text
    painter.setPen(QPen(QColor("black")))
    painter.drawText(rect_with_padding, Qt.AlignmentFlag.AlignCenter, text)

    painter.restore()

def render_error_message(painter: QPainter, view: QTransform, text: str): 
    if not text:
        return

    painter.save()

    # We want to draw in screen/view coordinates now
    painter.resetTransform()

    viewport = painter.viewport()
    center_x = viewport.width() / 2

    font = QFont("Arial", 15)
    font.setBold(True)
    painter.setFont(font)

    metrics = QFontMetrics(font)
    padding_x = 14
    padding_y = 8

    text_rect = metrics.boundingRect(text)
    box_w = text_rect.width() + padding_x * 2
    box_h = text_rect.height() + padding_y * 2

    box_x = center_x - box_w / 2
    box_y = 20

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(180, 30, 30, 220))
    painter.drawRoundedRect(box_x, box_y, box_w, box_h, 4, 4)

    painter.setPen(QColor('white'))
    painter.drawText(box_x, box_y, box_w, box_h, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()

def render_lasso(painter: QPainter, points: QPolygonF): 
    ui.lasso_pen.setStyle(Qt.DashLine)
    painter.setPen(ui.lasso_pen)
    painter.drawPolyline(points)

def render_brush(painter: QPainter, points: QPolygonF, brush: QPainterPath): 
    ui.lasso_pen.setStyle(Qt.DashLine)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(200,10,10,100)))
    all_points = points.toList()
    if len(all_points) > 2: 
        # One polygon approximation of the filled shape
        painter.drawPolygon(brush.toFillPolygon())

def render_rectangle_select(painter: QPainter, points: QPolygonF): 
    ui.lasso_pen.setStyle(Qt.DashLine)
    painter.setPen(ui.lasso_pen)
    painter.setBrush(Qt.NoBrush)
    all_points = points.toList()
    if len(all_points) >= 2: 
        rect = QRectF(all_points[0], all_points[-1])
        painter.drawRect(rect)

def render_highlighted_nodes(painter: QPainter, nodes: list[Node]): 
    painter.setPen(ui.active_pen)
    painter.setBrush(ui.active_brush)
    for node in nodes: 
        painter.drawEllipse(node.pos, 10, 10)

def polygon_with_holes(outer, holes=None):
    holes = holes if holes else []

    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    path.addPolygon(outer)

    for hole in holes:
        path.addPolygon(hole)
    return path

def render_group(painter: QPainter, group: Group,  move_group: bool, pivot_group: None | int): 
    ui.lasso_pen.setStyle(Qt.SolidLine)
    painter.setBrush(QBrush(QColor(200,10,10,100)))
    painter.setPen(ui.lasso_pen)
    
    # draw border 
    if group.hover_label_port == None and not group.show_labels: 
        for border_part in group.border: 
            path = polygon_with_holes(border_part[0], border_part[1:])
            painter.drawPath(path)
    
    # painter.drawRect(group.bounding_rect)

    painter.setPen(ui.button_pen)
    # draw pivot buttons 
    if not move_group and group.hover_label_port == None and not group.show_labels and len(group.pivot_buttons_pos) <= 5: 
        for i, button in enumerate(group.pivot_buttons_pos): 
            if type(pivot_group) == int and pivot_group != i: continue  
            painter.setBrush(QBrush(QColor('lightgreen')))
            painter.drawEllipse(button, 20, 20)
            painter.setBrush(Qt.NoBrush )
            open_dir = angle_from_points(button, group.pivot_nodes[i].pos) + 90
            draw_arc_with_arrows(painter, button, 40, arc_deg=90, open_direction_deg=open_dir)

    painter.setBrush(QBrush(QColor('red')))
    # draw middle buttons
    if pivot_group == None and group.hover_label_port == None and not group.show_labels: 
        move_but = group.move_button_pos
        painter.drawEllipse(move_but, group.button_size, group.button_size)
        renderer = QSvgRenderer("assets/move_icon.svg")
        icon_size = group.button_size + 10
        renderer.render(painter, 
                        QRectF(move_but.x() - 15, move_but.y() - icon_size/2, icon_size, icon_size))

    painter.setBrush(QBrush(QColor('lightblue')))
    if pivot_group == None and not move_group: 
        if group.hover_label_port == None and not group.show_labels: 
            # for expand button 
            expand_but = group.expand_button_pos
            painter.drawEllipse(expand_but, group.button_size, group.button_size)
            renderer = QSvgRenderer("assets/expand_rot.svg" if group.nodes[0].left_line else "assets/expand.svg")
            icon_size = group.button_size + 10
            renderer.render(painter, QRectF(expand_but.x() - 15, expand_but.y() - icon_size/2, icon_size, icon_size))

            # For lock button 
            lock_but = group.lock_button_pos
            painter.drawEllipse(lock_but, group.button_size, group.button_size)
            renderer = QSvgRenderer("assets/lock.svg" if group.check_locked_status() else "assets/unlock.svg")
            icon_size = group.button_size
            renderer.render(painter, QRectF(lock_but.x() - 10, lock_but.y() - icon_size/2, icon_size, icon_size))

            # For bend button 
            if group.deg_2 or group.circular:  
                shape_but = group.shape_button_pos
                painter.drawEllipse(shape_but, group.button_size, group.button_size)
                renderer = QSvgRenderer("assets/circle.svg" if group.circular else "assets/line.svg")
                icon_size = group.button_size
                renderer.render(painter, QRectF(shape_but.x() - 10, shape_but.y() - icon_size/2, icon_size, icon_size))

        # For label button 
        if group.hover_label_port == 8: 
            painter.setBrush(ui.highlight_brush)
        label_but = group.label_button_pos
        painter.drawEllipse(label_but, group.button_size, group.button_size)
        renderer = QSvgRenderer("assets/label.svg")
        icon_size = group.button_size - 2
        renderer.render(painter, QRectF(label_but.x() - 8, label_but.y() - icon_size/2 + 1, icon_size, icon_size))

        # Draw label rose 
        ui.rose_free_pen.setCosmetic(True)
        ui.rose_used_pen.setCosmetic(True)
        ui.active_handle_pen.setCosmetic(True)
    
        for i in range(8):
            if group.label_port_active == i: 
                painter.setBrush(ui.rose_used_brush)
            else:
                painter.setBrush(ui.rose_free_brush)

            if group.hover_label_port == i: 
                painter.setBrush(ui.highlight_brush)

            painter.drawEllipse( group.label_button_pos + 20*port_offset[i], 6, 6)

def angle_from_points(p1: QPointF, p2: QPointF) -> float:
    dx = p2.x() - p1.x()
    dy = p1.y() - p2.y() 
    return math.degrees(math.atan2(dy, dx))

def draw_arrow_head(painter: QPainter, tip: QPointF, direction_deg: float, size: float = 12, spread_deg: float = 28):
    a1 = math.radians(direction_deg + 180 - spread_deg)
    a2 = math.radians(direction_deg + 180 + spread_deg)

    p1 = QPointF(tip.x() + size * math.cos(a1), tip.y() - size * math.sin(a1))
    p2 = QPointF(tip.x() + size * math.cos(a2), tip.y() - size * math.sin(a2))

    painter.drawLine(tip, p1)
    painter.drawLine(tip, p2)

def draw_arc_with_arrows(painter: QPainter, center: QPointF, radius: float, arc_deg: float, open_direction_deg: float):
    
    rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)

    start_deg = open_direction_deg + arc_deg/2

    path = QPainterPath()
    path.arcMoveTo(rect, start_deg)
    path.arcTo(rect, start_deg, arc_deg)
    painter.drawPath(path)

    # endpoints from the path itself
    p_start = path.pointAtPercent(0.0)
    p_end = path.pointAtPercent(1.0)

    # nearby points to determine tangent direction
    eps = 0.01
    p_start_next = path.pointAtPercent(eps)
    p_end_prev = path.pointAtPercent(1.0 - eps)

    start_dir = angle_from_points(p_start, p_start_next) + 185
    end_dir = angle_from_points(p_end_prev, p_end) - 5

    draw_arrow_head(painter, p_start, start_dir)
    draw_arrow_head(painter, p_end, end_dir)


def render_concentric_circles(painter: QPainter): 
    #For displaying concentric circles 
    if ui.drag_node and len(ui.drag_node.edges) == 1:
        radius = ui.drag_node.edges[0].min_dist / 2
        
        for i in range(8, 0, -1): 
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0,0,0,5 * i)))
            painter.drawEllipse(ui.drag_node.pos, radius * i, radius * i)

            painter.setPen(QPen( QColor('white'), 3 ))
            painter.drawText(ui.drag_node.pos + ((radius * (i-0.5)) * port_offset[5]) + QPointF(-10, 0), str(i))

        painter.setPen(QPen( QColor('white'), 3 ))
        painter.drawLine(ui.drag_node.pos, ui.drag_node.pos + (radius * 8 * port_offset[5]))


def handle_position( v: Node, p: int ):
    return v.pos + ui.rose_radius*port_offset[p]

def handle_center_rose_position(v: Node, p: int): 
    assert p == 8 or p == 9
    if p == 8: return v.pos + (ui.rose_radius + ui.handle_radius + 10)*port_offset[2]
    else: return v.pos - (ui.rose_radius + ui.handle_radius + 10)*port_offset[2]

def handle_label_pos(point: QPointF, p: int): 
    if p is not None: 
        return point + 30*port_offset[p]
    else: 
        return point + 30*port_offset[0]
    
def handle_label_text_position(v: Node, p: int): 
    if p is not None: 
        if p in [0,1,2,7]: 
            return v.label_node.head
        else: 
            return v.label_node.end
    else: 
        return v.pos + QPointF(20, 0)

def free_edge_handle_position( v, e ):
    dir = e.direction(v).toPointF()
    return v.pos + 2*ui.rose_radius*dir

def is_hovered( v, i ):
    if v!=ui.hover_node: return False
    if v.ports[i] is None and i==ui.hover_empty_port: return True
    return ui.hover_edge is not None and v.ports[i]==ui.hover_edge

def draw_rose( painter, v: Node ):
    ui.rose_free_pen.setCosmetic(True)
    ui.rose_used_pen.setCosmetic(True)
    ui.active_handle_pen.setCosmetic(True)
    for i in range(8):
        if v.ports[i] is None:
            painter.setPen(ui.rose_free_pen)
            painter.setBrush(ui.rose_free_brush)
        else:
            painter.setPen(ui.rose_used_pen)
            painter.setBrush(ui.rose_used_brush)
        if ui.selected_node is not None:
            painter.setPen( ui.active_handle_pen )
        if ui.selected_node==v and ui.selected_edge is not None and ui.selected_edge==v.ports[i]:
            painter.setBrush(ui.rose_used_brush)
        if is_hovered( v, i ):
            painter.setBrush(ui.highlight_brush)
        painter.drawEllipse( handle_position(v,i), ui.handle_radius, ui.handle_radius )
    
    if ui.selected_node is not None and type(ui.selected_edge) == Label: 
        vert_dist = [(ui.rose_radius + ui.handle_radius + 5), -1 * (ui.rose_radius + ui.handle_radius + 15)]
        for i in range(2): 
            # for the horizontal center labels
            painter.setPen(ui.active_handle_pen)
            painter.setBrush(ui.rose_free_brush)
            if ui.hover_empty_port == i+8: 
                painter.setBrush(ui.highlight_brush)
            start = v.pos + QPointF(-2 * ui.handle_radius, vert_dist[i])
            painter.drawRect(start.x(), start.y(), 4 * ui.handle_radius, 10)

# Direction is always from p1 to p2 
def draw_indicator_lines(painter: QPainter, line: QLineF, min_edge_length: float, start: float = 0): 
    direction = QVector2D(line.p2() - line.p1()).normalized()
    normal = line.normalVector()
    normal = (QVector2D(normal.dx(), normal.dy()).normalized() * 4).toPointF()
    for i in range(int((line.length() - start)/min_edge_length)): 
        indicator_point = line.p1() + (direction * ((i+1) * min_edge_length + start)).toPointF()
        indicator_line = QLineF(indicator_point + normal, indicator_point - normal)
        painter.setPen( ui.node_pen )
        painter.drawLine(indicator_line)

def draw_locked_symbol(painter: QPainter, source: QPointF, dest: QPointF, length: float): 
    direction = QVector2D(dest - source).normalized()
    lock_pos = source + (direction * length).toPointF()
    renderer = QSvgRenderer("assets/lock_red.svg")
    icon_size = 10
    renderer.render(painter, QRectF(lock_pos.x() - icon_size/2, lock_pos.y() - icon_size/2, icon_size, icon_size))
