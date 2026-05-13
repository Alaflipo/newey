from __future__ import annotations 

from math import inf, atan2, pi, sqrt
import math 

import copy 

from PySide6.QtCore import QPointF, QLineF
from PySide6.QtGui import QVector2D
from PySide6.QtGui import QFont, QFontMetrics, QPolygonF, QPainterPath

def opposite_port( p ):
    return (p+4)%8

diag = 1/sqrt(2)

port_offset = [ QPointF(-1,0)
              , QPointF(-diag,diag)
              , QPointF(0,1)
              , QPointF(diag,diag)
              , QPointF(1,0)
              , QPointF(diag,-diag)
              , QPointF(0,-1)
              , QPointF(-diag,-diag)
              ]

class Network:
    def __init__(self, file_path = 'test.json'):
        self.file_path = file_path
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.metro_lines: dict[str, list[Edge]] = []

        # Midpoint of the network
        self.midpoint: QPointF = QPointF(0,0)
        self.layout_set: bool = False 

        self.geo_min_max = (0, 0, 0, 0)

        self.deg_2_lines: list[list[str]] = []

    def clone(self):
        other = Network()
        other.midpoint = self.midpoint
        other.layout_set = self.layout_set
        other.geo_min_max = self.geo_min_max
        other.deg_2_lines = self.deg_2_lines
        node_clones: dict[str, Node] = dict()
        for k,v in self.nodes.items():
            other_v = v.clone(v.pos.x(), v.pos.y(), v.name, v.label)
            other_label = v.label_node.clone(other_v, v.label)
            other_v.label_node = other_label
            if other_label.port is not None: 
                other_v.ports[other_label.port] = other_label
            node_clones[v] = other_v
            other.nodes[k] = other_v
        edge_clones = dict()
        for e in self.edges:
            a = other.nodes[ e.v[0].name ]
            b = other.nodes[ e.v[1].name ]
            other_e = Edge(a,b)
            other_e.color = e.color
            other_e.min_dist = e.min_dist
            other_e.max_dist = e.max_dist
            other_e.locked = e.locked
            edge_clones[e] = other_e
            a.edges.append( other_e )
            b.edges.append( other_e )
            other.edges.append( other_e )
            other_e.bend = e.bend
            other_e.port = e.port[:] # new copy of list

            # add edge to port list in node 
            if e.port[0] is not None: a.ports[e.port[0]] = other_e
            if e.port[1] is not None: b.ports[e.port[1]] = other_e

        return other

    def scale_by_shortest_edge( self, lb ):
        min_length = min([ e.geo_vector(e.v[0]).length() for e in self.edges ])
        factor = lb/min_length
        for v in self.nodes.values():
            v.update_pos(factor * v.pos, factor * v.geo_pos)
            
    def evict_all_edges(self):
        for v in self.nodes.values():
            for e in v.edges:
                v.try_evict(e)
    
    def evict_all_labels(self): 
        for v in self.nodes.values():
            v.evict_label()

    def get_label_nodes(self): 
        node_labels: list[Node] = []
        for v in self.nodes.values():
            node_labels.append(v.label_node)
        return node_labels
    
    def calculate_mid_point(self): 
        self.midpoint = midpoint([node.geo_pos for node in self.nodes.values()])

        for line in self.deg_2_lines: 
            midpoint_line: QPointF = midpoint([self.nodes[node_name].geo_pos for node_name in line])
            for node_name in line: 
                self.nodes[node_name].left_line = midpoint_line.x() <= self.midpoint.x()

    # returns either two label vertices that overlap or one vertex that overlaps with an edge
    def check_label_overlaps(self): 
        overlaps: list[tuple[Node]] = []
        for v1 in self.nodes.values(): 
            for v2 in self.nodes.values(): 
                if v1 == v2: continue 
                if (v2, v1) in overlaps: continue 
                if v1.label_node.overlaps(v2.label_node): 
                    overlaps.append((v1,v2))
            for edge in self.edges: 
                if v1.label_node.overlaps_edge(edge): 
                    overlaps.append([v1])
        return overlaps 
    
    def labels_overlaps_label(self, rect: QPolygonF): 
        for v in self.nodes.values(): 
            if v.label_node.rectangle_points.intersects(rect): 
                return True
        return False 
    
    def edges_overlaps_label(self, rect: QPolygonF): 
        for edge in self.edges: 
            if len(edge.v) == 2 and rect.intersects(QPolygonF([edge.v[0].pos, edge.v[1].pos])): 
                return True 
        return False 
    
    def overlaps_with_label(self, rect: QPolygonF): 
        return self.edges_overlaps_label(rect) or self.labels_overlaps_label(rect)

    def find_degree_2_lines(self): 
        self.deg_2_lines: list[list[str]] = []
        seen: dict = dict()
        for name, v in self.nodes.items(): 
            if name in seen: continue

            if len(v.edges) == 2:
                seen[name] = True 

                path1 = spacewalk( v.edges[0].other(v), v, seen )
                path2 = spacewalk( v.edges[1].other(v), v, seen )
                walk: list[Node] = [node.name for node in path1] + [v.name] + [v.name for v in reversed(path2)]
                self.deg_2_lines.append(walk)
            else: # We skip degree 1 and > 2 because they will be taken into account with one of the walks 
                continue 

    def find_min_max_geo(self): 
        min_x, min_y = math.inf, math.inf
        max_x, max_y = -math.inf, -math.inf
        for _, v in self.nodes.items():
            min_x = min(min_x, v.geo_pos.x())
            min_y = min(min_y, v.geo_pos.y())
            max_x = max(max_x, v.geo_pos.x())
            max_y = max(max_y, v.geo_pos.y())
        self.geo_min_max = (min_x, max_x, min_y, max_y)

    def set_background_image(self): 
        min_x, min_y = math.inf, math.inf
        max_x, max_y = -math.inf, -math.inf
        for _, v in self.nodes.items():
            min_x = min(min_x, v.pos.x())
            min_y = min(min_y, v.pos.y())
            max_x = max(max_x, v.pos.x())
            max_y = max(max_y, v.pos.y())
        
        min_x_geo, max_x_geo, min_y_geo, max_y_geo = self.geo_min_max
        for _, v in self.nodes.items(): 
            new_x = min_x + (v.geo_pos.x() - min_x_geo) * (max_x - min_x) / (max_x_geo - min_x_geo)
            new_y = min_y + (v.geo_pos.y() - min_y_geo) * (max_y - min_y) / (max_y_geo - min_y_geo)
            v.background_pos = QPointF(new_x, new_y)
            
    def divide_in_lines(self): 
        self.lines: dict[str, list[Node]] = {}
        for edge in self.edges: 
            for color in edge.color: 
                if color in self.lines: 
                    if not edge.v[0] in self.lines[color]: self.lines[color].append(edge.v[0])
                    if not edge.v[1] in self.lines[color]: self.lines[color].append(edge.v[1])
                else: 
                    self.lines[color] = [edge.v[0], edge.v[1]]
    
    def ports_set(self): 
        for edge in self.edges: 
            if edge.port[0] == None or edge.port[1] == None: 
                return False 
        return True 

class Node:
    def __init__(self, x, y, name: str, label:str = ""):
        self.pos: QPointF = QPointF(x,y)
        self.geo_pos: QPointF = self.pos
        self.background_pos: QPointF = self.pos
        self.name: str = name
        self.label: str = label

        # Used for labeling
        self.label_node: Label = Label(self, label) 

        self.edges: list[Edge] = []
        self.ports: list[Edge | None | Label] = [None]*8

        self.left_line: bool = True 

        self.locked: bool = False 

        self.bend_penalty: float = 0 
        self.label_hor: float = 10
        self.label_same_side: float = 10

    # Still need to add label_node and edges (edges and ports) on your own 
    def clone(self, x, y, name, label) -> Node:
        other = Node(x, y, name, label)
        other.geo_pos = self.geo_pos
        other.pos = self.pos 
        other.left_line = self.left_line
        other.locked = self.locked
        return other 
    
    def update_pos(self, pos: QPointF, geo_pos: QPointF): 
        self.pos = pos 
        self.geo_pos = geo_pos
        self.label_node.update_pos(pos, geo_pos)

    def lock(self): 
        self.locked = True 
        
    def unlock(self): 
        self.locked = False 

    def isfree(self, port: int) -> bool: 
        return self.ports[port] == None 

    def set_position( self, x, y ):
        self.pos = QPointF(x,y)

    def neighbors(self):
        return [e.other(self) for e in self.edges]
    
    def sort_edges_by_geo(self):
        self.edges.sort(key=lambda e: e.geo_angle(self))
    def sort_edges(self):
        self.edges.sort(key=lambda e: e.angle(self))

    def set_label(self, port_number: int | None): 
        if port_number is not None: 
            self.port_number_label = port_number

    def assign(self, e: Edge, i: int, force=False) -> bool:
        if type(self.ports[i]) == Label: 
            self.evict_label()
            new_port = self.first_free_port(exceptions=[i])
            self.assign_label(new_port)
        elif self.ports[i] is not None:
            if force: self.evict(self.ports[i])
            else: return False
        me = e.id(self)
        old_port = e.port[me]
        if old_port is not None: self.ports[old_port] = None
        e.port[me] = i
        self.ports[i] = e
        return True
    
    def assign_both_ends( self, e: Edge, i: int, force=False ):
        self.assign(e,i,force)
        e.other(self).assign( e, opposite_port(i), force )

    def evict( self, e: Edge ):
        me = e.id(self)
        # assert self.ports[e.port[me]] == e
        self.ports[e.port[me]] = None
        e.port[me] = None
        e.bend = None
    
    def evict_all(self, exceptions: list[Edge]): 
        for item in self.ports: 
            if item in exceptions: continue
            if type(item) == Edge: self.evict(item)
            if type(item) == Label: self.evict_label()

    def assign_label(self, new_port, hor=False): 
        # First make sure that the label is evicted (if there is a new edge there we leave it)
        if self.label_node.port is not None and (type(self.ports[self.label_node.port]) == Label): 
            self.ports[self.label_node.port] = None 
        self.label_node.center_label = hor
        self.label_node.port = new_port
        self.ports[new_port] = self.label_node 
        # don't know if this always necessary, can be removed if slow
        self.label_node.update_label_border()

    def evict_label(self): 
        if self.label_node.port is not None: 
            self.ports[self.label_node.port] = None 
            self.label_node.port = None 

    # If the edge is connected to the vertex it will evict it 
    def try_evict( self, e: Edge ):
        if not e.free_at(self): self.evict(e)
    
    def is_deg2(self): 
        return len(self.edges) == 2

    def straighten_deg2( self, e: Edge ):

        port = e.port[e.id(self)]
        label_port = self.label_node.port 

        # If the label is in the direction of the straigten call we choose a different port 
        if label_port == opposite_port(port): 
            label_port = self.first_free_port(exceptions=[label_port])

        v = e.other(self)
        v.assign_label(label_port)
        while len(v.edges)==2:
            if v==self: break # loop?
            prev_e = e
            e = v.edges[0] if v.edges[0]!=prev_e else v.edges[1]
            # Make sure that the label port is reassigned to the port position of the first vertex in the straigten call
            e.other(v).assign_label(label_port)
            v.assign_both_ends(e,port,force=True)
            v = e.other(v)

    def is_straight_through( self ):
        if len(self.edges)==2:
            a = self.edges[0].port_at(self)
            b = self.edges[1].port_at(self)
            return a==opposite_port(b)

    def is_right_angle( self ):
        if len(self.edges)==2:
            a = self.edges[0].port_at(self)
            b = self.edges[1].port_at(self)
            return (a+2)%8==b or (b+2)%8==a
        else: return False

    def smoothen( self ):
        if self.is_right_angle():
            a = self.edges[0].port_at(self)
            b = self.edges[1].port_at(self)
            if (a+2)%8==b: a = (a-1)%8
            else: a = (a+1)%8
            self.assign(self.edges[0],a)
            self.assign(self.edges[1],opposite_port(a))
        else: return False

    def get_free_ports(self, ignore_label=False): 
        free_ports = []
        for i, port in enumerate(self.ports): 
            if port == None: free_ports.append(i)
            if type(port) == Label and ignore_label: free_ports.append(i)
        return free_ports
    
    def get_occupied_ports(self, ignore_label=False) -> list[int]: 
        occupied = []
        for i, item in enumerate(self.ports): 
            if type(item) == Edge: occupied.append(i)
            if type(item) == Label and not ignore_label: occupied.append(i)
        return occupied
    
    def first_free_port(self, exceptions=[]): 
        for i, port in enumerate(self.ports): 
            if i in exceptions: 
                continue 
            if port is None: 
                return i 
        return None 
    
    def rad_to_port(self, angle:float): 
        areas = [((1 + 2*i) * pi)/ 8 for i in range(8)]
        for i in range(len(areas) - 1): 
            if angle >= areas[i] and angle <= areas[i+1]: 
                return (7 - i)
        return 0  
    
    def check_for_closer_port(self, pos: QPointF):
        dx = self.pos.x() - pos.x()
        dy = self.pos.y() - pos.y()
        angle_rad = math.atan2(dy, dx)  
        angle_rad = angle_rad % (2 * math.pi)
        return self.rad_to_port(angle_rad)

class Label: 

    def __init__(self, node: Node, label: str):
        self.label_text: str = label
        self.text_width = self.measure_text_width()
        self.center_label: bool = False 

        self.node: Node = node 
        self.head: QPointF = node.pos + QPointF(self.text_width, 10)
        self.geo_head: QPointF = self.head
        self.end: QPointF = node.pos
        
        self.port: int | None = None 

        self.rectangle_points: QPolygonF = QPolygonF()

    def clone(self, node, label) -> Label: 
        other = Label(node, label)
        other.head = self.head 
        other.geo_head = self.geo_head
        other.end = self.end 
        other.port = self.port
        other.rectangle_points = QPolygonF(self.rectangle_points)
        other.center_label = self.center_label
        return other
    
    def measure_text_width(self): 
        font = QFont("Arial", 15)
        metrics = QFontMetrics(font)
        return metrics.horizontalAdvance(self.label_text)
    
    def get_rectangle_port(self, port: int, label_dist: int) -> QPolygonF: 
        start = self.node.pos + (label_dist * port_offset[port])
        end = self.node.pos + ((self.text_width + label_dist) * port_offset[port])
        return self.get_label_border(start, end)
    
    def update_pos(self, pos: QPointF, geo_pos: QPointF): 
        self.head: QPointF = pos
        self.geo_head: QPointF = geo_pos
        self.end: QPointF = pos
    
    def set_pos_by_port(self, p: int): 
        self.head = self.end + ((self.text_width + 20) * port_offset[p])
    
    def set_position( self, x, y ):
        self.head = QPointF(x,y)

        if self.port != None: 
            self.end = self.head + (self.text_width * port_offset[opposite_port(self.port)])
        
        self.rectangle_points = self.get_label_border(self.head, self.end)

    def update_label_border(self): 
        self.rectangle_points = self.get_label_border(self.head, self.end)

    def get_label_border(self, start: QPointF, end: QPointF) -> QPolygonF:
        normal = QLineF(start, end).normalVector()
        # The box height is 20 so we multiply by 10
        vector = (QVector2D(normal.dx(), normal.dy()).normalized() * 10).toPointF()
        rectangle_points = [end + vector, end - vector, start - vector, start + vector]
        return QPolygonF(rectangle_points)

    def overlaps(self, other: Label): 
        return self.rectangle_points.intersects(other.rectangle_points) 
    
    def overlaps_edge(self, edge: Edge): 
        if len(edge.v) == 2: 
            return self.rectangle_points.intersects(QPolygonF([edge.v[0].pos, edge.v[1].pos]))
        return False 


class Edge:
    def __init__(self, a, b):
        self.v: list[Node] = [a,b]
        self.port: list[None | int] = [None,None]
        self.bend: None | QPointF = None
        self.color: str = '000000'
        self.line_id: str = ''

        self.min_dist: int = 100
        self.max_dist: int | None = None 

        self.locked: bool = False
    
    def id(self,v):
        if self.v[0]==v: return 0
        if self.v[1]==v: return 1
        assert False

    def other(self, v):
        if self.v[0]==v: return self.v[1]
        if self.v[1]==v: return self.v[0]
        assert False

    def port_at(self, v):
        if self.v[0]==v: return self.port[0]
        if self.v[1]==v: return self.port[1]
        assert False

    # returns whether the edge is actually connected to v 
    def free_at(self,v):
        return self.port[self.id(v)]==None
    
    def has_no_port(self): 
        return self.port[0] == None or self.port[1] == None
    
    def length(self) -> float: 
        return sqrt((self.v[0].pos.x()-self.v[1].pos.x())**2 + (self.v[0].pos.y()-self.v[1].pos.y())**2)
    # returns the length of the two parts of a line when bend
    # v depends the order of the length pieces 
    def length_bend(self, node: Node) -> tuple[float]: 
        assert self.bend
        first_part = sqrt((node.pos.x()-self.bend.x())**2 + (node.pos.y()-self.bend.y())**2)
        second_part = sqrt((self.bend.x()-self.other(node).pos.x())**2 + (self.bend.y()-self.other(node).pos.y())**2)
        return (first_part, second_part)
    
    # (scaled) normal vector as point
    def normal(self, scale=1): 
        normal = QLineF(self.v[0].pos, self.v[1].pos).normalVector()
        return (QVector2D(normal.dx(), normal.dy()).normalized() * scale).toPointF()

    def direction(self,v):
        return QVector2D(self.v[1-self.id(v)].pos - v.pos).normalized()
    def geo_direction(self,v):
        return QVector2D(self.v[1-self.id(v)].geo_pos - v.geo_pos).normalized()
    
    def vector(self,v):
        return QVector2D(self.v[1-self.id(v)].pos - v.pos)
    def geo_vector(self,v):
        return QVector2D(self.v[1-self.id(v)].geo_pos - v.geo_pos)

    # CCW angles, start at 0 = left
    def angle(self,v):
        dir = self.vector(v)
        return pi-atan2(dir.y(),dir.x())
    def geo_angle(self,v):
        dir = self.geo_vector(v)
        return pi-atan2(dir.y(),dir.x())
    
    def consistent_ports(self):
        return self.port[0]==opposite_port(self.port[1])
    
    def give_parralel_line(self, offset): 
        normal = self.normal()

        new_p0 = self.v[0].pos + offset * normal
        new_p1 = self.v[1].pos + offset * normal

        return (new_p0, new_p1)
    
    def give_point_offset(self, point, offset): 
        return point + offset * self.normal()
    
    def toggle_locked(self): 
        self.locked = not self.locked

    def lock(self): 
        self.locked = True
    
    def unlock(self): 
        self.locked = False

def round_angle_to_port(angle):
    return int(((angle+pi/8)%(2*pi))/(pi/4))

def midpoint(points: list[QPointF]): 
    sum_x = 0 
    sum_y = 0 
    for v in points:
        sum_x += v.x()
        sum_y += v.y()
    return QPointF(sum_x / len(points), sum_y / len(points))

def spacewalk( v: Node, prev, seen ) -> list[Node]:
    seen[v.name] = True
    walk = []
    if v.is_deg2():
        v0 = v.edges[0].other(v)
        v1 = v.edges[1].other(v)
        next = v0 if v1==prev else v1
        # We want to add deg 1 and deg > 2 to the walk because they do belong to the part of the metro line
        if next.is_deg2():
            if not next.name in seen:
                walk = spacewalk( next, v, seen )
        else: 
            walk.append(next)
    walk.append(v)
    return walk
