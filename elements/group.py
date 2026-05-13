from __future__ import annotations 

from PySide6.QtGui import Qt, QPolygonF, QVector2D
from PySide6.QtCore import QPointF, QRectF, QLineF

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union, polygonize

from collections import deque

from elements.network import Node, Edge, Network
from math import sqrt

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

class Group: 

    def __init__(self, nodes: list[Node], name: str = '', color = None, bend=0, hor=0, same_side=0):
        self.nodes: list[Node] = nodes 
        self.conn_edges: list[Edge] = []
        self.conn_nodes: list[Node] = []
        self.pivot_edges: list[Edge] = []
        self.pivot_nodes: list[Node] = []
        
        self.find_conn_edge_nodes()

        self.name: str = name 
        self.color: str | None = color

        self.button_size = 20

        self.internal_edges = self.find_all_edges()
        self.find_degree_2_lines()

        # Buttons 
        self.pivot_buttons_pos: list[QPointF] = []
        self.move_button_pos: QPointF | None = None 
        self.expand_button_pos: QPointF | None = None 
        self.lock_button_pos: QPointF | None = None 
        self.label_button_pos: QPointF | None = None 
        self.shape_button_pos: QPointF | None = None 

        self.label_port_active: int | None = None 
        self.hover_label_port: int | None = None 

        # Slider values 
        self.bend_pentalty: float = bend
        self.label_hor: float = hor
        self.label_same_side: float = same_side

        self.show_labels: bool = False 

        self.deg_2 = self.is_deg_2()
        self.circular = self.is_circular()

        self.update_group()

    def find_conn_edge_nodes(self): 
        # Find an edge that connects the group to a node outside the group
        for v in self.nodes:
            has_external = False 
            internal: list[Edge] = []
            for e in v.edges:
                other_node = e.other(v)
                if other_node not in self.nodes:
                    has_external = True 
                    self.conn_edges.append(e)
                    self.conn_nodes.append(other_node)
                else: internal.append(e)
            if has_external: 
                self.pivot_edges += internal
                self.pivot_nodes += [v] * len(internal)

    def update_group(self): 
        self.update_border()
        self.determine_pivot_buttons()

    def clone(self, network: Network) -> Group:
        group_node_names = [group_node.name for group_node in self.nodes]
        new_group_nodes = [v for v in network.nodes.values() if v.name in group_node_names]
        new_group = Group(new_group_nodes, name=self.name, color=self.color)
        new_group.bend_pentalty = self.bend_pentalty
        new_group.label_hor = self.label_hor
        new_group.label_same_side = self.label_same_side
        return new_group

    def can_be_moved(self) -> bool: 
        return len(self.conn_nodes) > 0
    
    def has_point_in_center(self, point) -> bool: 
        dist = QVector2D(self.move_button_pos - point).length()
        # size of center point on screen
        return dist < self.button_size
    
    def has_point_in_expand(self, point) -> bool: 
        dist = QVector2D(self.expand_button_pos - point).length()
        return dist < self.button_size
    
    def has_point_in_lock(self, point) -> bool: 
        dist = QVector2D(self.lock_button_pos - point).length()
        return dist < self.button_size

    def has_point_in_shape(self, point) -> bool: 
        dist = QVector2D(self.shape_button_pos - point).length()
        return dist < self.button_size
    
    def has_point_in_pivot_button(self, point) -> bool: 
        for i, button in enumerate(self.pivot_buttons_pos): 
            dist = QVector2D(button - point).length()
            # size of center point on screen
            if dist < self.button_size: 
                return i 
        return None 
    
    def handle_port_offset(self, pos: QPointF, p: int): 
        return pos + 20*port_offset[p]
    
    def has_point_in_label_button(self, point) -> int | None: 
        dist_button = QVector2D(self.label_button_pos - point).length()

        # If we are outside of this range we are not close to any label
        if dist_button > self.button_size * 2: 
            self.hover_label_port = None
            return None 

        # check if we are over each port 
        for i in range(8):
            dist = QVector2D(self.handle_port_offset(self.label_button_pos, i) - point).length()

            if dist < 6:
                self.hover_label_port = i
                return i
            
        # we clicked in the middle of the button
        if dist_button < self.button_size: 
            self.hover_label_port = 8
            return 8

        return None 
    
    def get_slider_values(self) -> tuple: 
        return (self.bend_pentalty, self.label_hor, self.label_same_side)
    
    def update_bend_penalty(self, value): 
        self.bend_pentalty = value
        for node in self.nodes: 
            node.bend_penalty = value 
        self.show_labels = False 
    
    def update_hor_label(self, value): 
        self.label_hor = value
        for node in self.nodes: 
            node.label_hor = value 
        self.show_labels = True 

    def update_same_side_label(self, value): 
        self.label_same_side = value
        for node in self.nodes: 
            node.label_same_side = value 
        self.show_labels = True 

    def circular_diff(self, a, b, n=8):
        return (b - a + n//2) % n - n//2

    def pivot(self, mouse_pos: QPointF, button_index: int) -> tuple[QPointF | None, int]: 
        
        outside_v = self.pivot_nodes[button_index]
        outside_e = self.pivot_edges[button_index]

        closer_port = outside_v.check_for_closer_port(mouse_pos)

        # Only rotate the group if the target port differs from the current one
        if closer_port != outside_e.port_at(outside_v) and closer_port in outside_v.get_free_ports(ignore_label=True): 
            # Determine rotation direction: clockwise or counterclockwise
            distance = self.circular_diff(outside_e.port_at(outside_v), closer_port)

            # rotate all nodes in the group by shifting ports in the same direction
            # for v in self.nodes: 
            #     v.lock()
            #     # if v in self.pivot_nodes: continue 
            #     # we skip the pivot points

            #     new_label_port = (v.label_node.port + distance) % 8
            #     # reassign all internal edges connected to other nodes in the group
            #     for e in v.edges: 
            #         other_v = e.other(v)
            #         if other_v in self.nodes: 
            #             v.assign(e, (e.port_at(v) + distance) % 8)

            #     # reassign the node label to the rotated port
            #     if v.ports[new_label_port] == None: 
            #         v.assign_label(new_label_port)
            #     else: 
            #         v.assign_label(v.first_free_port())

            for v in self.nodes: 
                v.lock()

                new_label_port = (v.label_node.port + distance) % 8
                new_ports: list[tuple[Edge, int, int]] = []
                exceptions = []
                for e in v.edges: 
                    if e in self.conn_edges: 
                        exceptions.append(e)
                    else: 
                        new_ports.append((e, (e.port_at(v) + distance) % 8, e.port_at(v)))
                v.evict_all(exceptions = exceptions)

                for e, port, old_port in new_ports: 
                    if not v.assign(e, port): 
                        v.assign(e, old_port)


                if v.ports[new_label_port] == None: 
                    v.assign_label(new_label_port)
                else: 
                    v.assign_label(v.first_free_port())
            
            # for e in self.internal_edges: 
            #     v1 = e.v[0]
            #     new_port = 
            #     v1.assign(e, (e.port_at(v1) + distance) % 8)

            #     v2 = e.v[1]
            #     v2.assign(e, (e.port_at(v2) + distance) % 8)

            # for v in self.nodes: 
            #     v.lock()
            #     new_label_port = (v.label_node.port + distance) % 8
            #     v.assign_label(new_label_port)
                

            # for i in range(len(self.pivot_edges)): 
            #     new_port = (self.pivot_edges[i].port_at(self.pivot_nodes[i]) + distance) % 8
            #     if new_port in self.pivot_nodes[i].get_free_ports(ignore_label=True):
            #         self.pivot_nodes[i].assign_both_ends(self.pivot_edges[i], new_port)

            # new_outside_port = (outside_e.port_at(outside_v) + distance) % 8
            # if new_outside_port in outside_v.get_free_ports(ignore_label=True):
            #         outside_v.assign_both_ends(outside_e, new_outside_port)

            # reassign the outside edge at the external node to complete the pivot
            # for i in range(len(self.pivot_edges)): 
            #     new_port = (self.pivot_edges[i].port_at(self.pivot_nodes[i]) + distance) % 8
            #     if new_port in self.pivot_nodes[i].get_free_ports(ignore_label=True):
            #         self.pivot_nodes[i].assign_both_ends(self.pivot_edges[i], new_port)
            
            return outside_v.pos, 45 * distance 
        
        return None, 0 

    def move(self, mouse_pos) -> bool : 

        closer_ports = []

        for i in range(len(self.conn_nodes)): 
            outside_v = self.conn_nodes[i]
            outside_e = self.conn_edges[i]

            closer_port = outside_v.check_for_closer_port(mouse_pos)

            if closer_port != outside_e.port_at(outside_v): 
                closer_ports.append(closer_port)

        # if not for every conn node a new port is found, we wait
        if len(closer_ports) != len(self.conn_nodes): 
            return False  
        
        for i in range(len(self.conn_nodes)): 
            outside_v = self.conn_nodes[i]
            outside_e = self.conn_edges[i]

            outside_v.assign_both_ends(outside_e, closer_ports[i])
        
        for v in self.nodes: 
            v.lock()
        
        return True 

            # cc_wise = 1 if closer_ports[i] > outside_e.port_at(outside_v) else -1
            # outside_v.assign_both_ends(outside_e, (outside_e.port_at(outside_v) + cc_wise) % 8)
    
    def expand(self, pos: QPointF): 
        vec = QVector2D(pos - self.expand_button_pos)
        size = self.button_size
        is_left = self.nodes[0].left_line

        expand = vec.y() < -size and (vec.x() < size if is_left else vec.x() > size)
        shrink = vec.y() > size and (vec.x() > -size if is_left else vec.x() < -size)

        if expand or shrink:
            largest_edge = max(self.internal_edges, key=lambda edge: edge.length(), default=None)
            for edge in self.internal_edges:
                length = edge.length()
                resize_factor = length / largest_edge.length()
                error_margin = 1 / largest_edge.length()

                if expand:
                    if not edge.locked: edge.min_dist = length
                    else: edge.min_dist = edge.min_dist + resize_factor
                    edge.max_dist = edge.min_dist + error_margin

                elif shrink:
                    if not edge.max_dist:
                        edge.max_dist = length
                    edge.max_dist -= resize_factor
                    edge.min_dist = edge.max_dist - error_margin

            self.lock_edges()
                

        #### OLD VERSION WITH ONLY MIN_DIST: This provides more freedom but less precise manipulation

        # vec = QVector2D(pos - self.expand_button_pos)
        # if self.nodes[0].left_line: 
        #     if vec.x() < self.button_size and vec.y() < -self.button_size: 
        #         for edge in self.internal_edges: 
        #             edge.min_dist += 1
        #     if vec.x() > -self.button_size and vec.y() > self.button_size: 
        #         for edge in self.internal_edges: 
        #             edge.min_dist -= 1
        # else: 
        #     if vec.x() > self.button_size and vec.y() < -self.button_size: 
        #         for edge in self.internal_edges: 
        #             edge.min_dist += 1
        #     if vec.x() < -self.button_size and vec.y() > self.button_size: 
        #         for edge in self.internal_edges: 
        #             edge.min_dist -= 1

    def check_locked_status(self) -> bool: 
        locked: int = 0 
        for v in self.nodes: 
            if v.locked: locked += 1
        return locked > len(self.nodes)/2

    # we lock if the majority is unlocked and the other way around
    def toggle_lock(self): 
        locked = self.check_locked_status()
        for v in self.nodes: 
            if locked: v.unlock()
            else: v.lock()
        for e in self.internal_edges: 
            if locked: e.unlock()
        return locked 

    def lock_edges(self): 
        for e in self.internal_edges: 
            e.lock()

    def set_group_labels(self): 
        if self.hover_label_port == None: return 

        self.label_port_active = self.hover_label_port
        for v in self.nodes: 
            if v.isfree(self.label_port_active): 
                v.assign_label(self.label_port_active)
        return self.label_port_active
    
    def find_degree_2_lines(self): 
        self.deg_2_lines: list[list[Node]] = []
        seen: dict = dict()
        for v in self.nodes: 
            if v in seen: continue

            if v.is_deg2() and len(self.internal[v]) == 2:
                seen[v] = True 

                path1 = self.spacewalk( self.internal[v][0].other(v), v, seen )
                path2 = self.spacewalk( self.internal[v][1].other(v), v, seen )
                walk: list[Node] = path1 + [v] + list(reversed(path2))
                self.deg_2_lines.append(walk)
            else: # We skip degree 1 and > 2 because they will be taken into account with one of the walks 
                continue 
    
    def spacewalk(self, v: Node, prev, seen ) -> list[Node]:
        seen[v] = True
        walk = []

        if v.is_deg2() and len(self.internal[v]) == 2:
            v0 = v.edges[0].other(v)
            v1 = v.edges[1].other(v)
            next = v0 if v1==prev else v1
            # We want to add deg 1 and deg > 2 to the walk because they do belong to the part of the metro line
            if next.is_deg2() and len(self.internal[next]) == 2:
                if not next in seen:
                    walk = self.spacewalk( next, v, seen )
            elif next in self.internal: 
                walk.append(next)
        walk.append(v)
        return walk
    
    def amount_internal_edges(self, node: Node): 
        amount = 0 
        for edge in node.edges: 
            if edge in self.internal_edges: 
                amount += 1
        return amount 
    
    def create_shape(self): 
        success = False 
        if self.deg_2: 
            success = self.straighten()
        elif self.circular: 
            success = self.circlelize()
        return success

    def is_deg_2(self): 
        end_points = 0 
        for node in self.nodes: 
            if len(self.internal[node]) > 2 or len(self.internal[node]) <= 0: 
                return False 
            if len(self.internal[node]) == 1: 
                end_points += 1 
            if end_points > 2: return False 
        if end_points != 2: return False 
        return True 
    
    def is_circular(self): 

        # can't have a cycle when terhe are les then 3 nodes
        if len(self.nodes) <= 2: return False 

        # every node must have degree 2
        for node in self.nodes:
            if len(self.internal[node]) != 2:
                return False
            
        # check if it is connected
        visited = set()
        q = deque([self.nodes[0]])
        
        while q:
            node = q.popleft()
            if node in visited:
                continue
            visited.add(node)
            for edge in self.internal[node]:
                other = edge.other(node)
                if other not in visited:
                    q.append(other)
        
        return len(visited) == len(self.nodes)
    

    def straighten(self): 
        ports: dict[int, list[Edge]] = {}
        for edge in self.internal_edges: 
            port1 = edge.port_at(edge.v[0])
            port2 = edge.port_at(edge.v[1])
            min_port = min(port1, port2)
            if min_port in ports: 
                ports[min_port].append(edge)
            else: 
                ports[min_port] = [edge]
        max_port = max(ports, key=lambda port: len(ports[port]))
        common_edge = ports[max_port][0]

        for node in common_edge.v: 
            edge = common_edge
            port = edge.port_at(node)
       
            label_port = node.label_node.port 

            # If the label is in the direction of the straigten call we choose a different port 
            if label_port == opposite_port(port): 
                label_port = node.first_free_port(exceptions=[label_port])
            v = edge.other(node)
            v.assign_label(label_port)

            while v in self.nodes and self.amount_internal_edges(v) >= 2:
                prev_e = edge
                for e in v.edges: 
                    if e in self.internal_edges and e != prev_e: 
                        edge = e
                        break 
                # Make sure that the label port is reassigned to the port position of the first vertex in the straigten call
                edge.other(v).assign_label(label_port)

                # generate closest ports to the current port and check them all 
                ports_to_check = self.closest_ports(port)
                for p in ports_to_check: 
                    occ1 = v.is_occupied(p)
                    occ2 = edge.other(v).is_occupied(opposite_port(p))
                    if (occ1 is None or occ1 == edge) and (occ2 is None or occ2 == edge):
                        v.assign_both_ends(edge,p,force=False) 
                        break 
                v.lock()
                v = edge.other(v)
                v.lock()
        return True 
    
    def closest_ports(self, port) -> list[int]: 
        ports = [port]
        n = 8

        for i in range(1, n):
            if i % 2 == 1:
                ports.append((port + (i + 1) // 2) % n)
            else:
                ports.append((port - i // 2) % n)
        return ports 

    def generate_circle_sequence(self, length):
        # the port sequence of the first 8 nodes
        base_seq = [
            [4,1,7], 
            [4,6,0,2],
            [4,5,7,1,3], 
            [4,5,7,0,1,3], 
            [4,5,6,7,1,2,3],
            [4,5,6,7,0,1,2,3],
        ]
        if length <= 8: 
            return base_seq[length - 3]
        
        # from here there is a logical sequence to follow 
        base = base_seq[5]
        dup_order = [4, 0, 6, 2, 5, 1, 7, 3]
        
        seq = base.copy()
        i = 0
        
        while len(seq) < length:
            val = dup_order[i % len(dup_order)]
            idx = seq.index(val)
            seq.insert(idx, val)
            i += 1
        
        return seq[:length]

    def circlelize(self): 
        min_nodes = [self.nodes[0]]
        for node in self.nodes[1:]: 
            if node.pos.y() > min_nodes[0].pos.y(): 
                min_nodes = [node]
            elif node.pos.y() == min_nodes[0].pos.y(): 
                min_nodes.append(node)
        
        left_node = min(min_nodes, key=lambda node: node.pos.x())
        right_edge = min(self.internal[left_node], key=lambda edge: abs(self.circular_diff(4, edge.port_at(left_node))))

        sequence = self.generate_circle_sequence(len(self.nodes))

        node = left_node 
        edge = right_edge 
        for port in sequence: 
            node.assign_both_ends(edge,port,force=False)
            node = edge.other(node)
            edge = self.internal[node][0] if self.internal[node][0] != edge else self.internal[node][1]

        return True 

    def find_all_edges(self) -> list[Edge]:
        edges: list[Edge] = []
        self.internal : dict[Node, list[Edge]] = {}
        for node in self.nodes: 
            self.internal[node] = []
            for edge in node.edges: 
                if edge.other(node) in self.nodes: 
                    self.internal[node].append(edge)
                    if edge not in edges: 
                        edges.append(edge)
        return edges 
    
    def update_border(self): 
        node_cloud = QPolygonF([node.pos for node in self.nodes])
        self.bounding_rect = node_cloud.boundingRect()
        self.move_button_pos = self.bounding_rect.center()
        if self.nodes[0].left_line: 
            self.expand_button_pos = QPointF(self.bounding_rect.topLeft().x() - 60, self.bounding_rect.topLeft().y() - 60)
        else: 
            self.expand_button_pos = QPointF(self.bounding_rect.topRight().x() + 60, self.bounding_rect.topRight().y() - 60)
        self.lock_button_pos = QPointF(self.bounding_rect.center().x() - 50, self.bounding_rect.bottom() + 60)
        self.label_button_pos = QPointF(self.bounding_rect.center().x(), self.bounding_rect.bottom() + 60)
        self.shape_button_pos = QPointF(self.bounding_rect.center().x() + 50, self.bounding_rect.bottom() + 60)

        # If the border only exists of nodes and no edges 
        self.border = []
        if len(self.internal_edges) == 0: 
            for node in self.nodes: 
                geom = Point(node.pos.x(), node.pos.y()).buffer(30, cap_style=1, join_style=1)
                border_part = [QPolygonF([QPointF(x, y) for x, y in geom.exterior.coords])]
                self.border.append(border_part)
            return 

        # if the border exists of nodes and edges 
        lines: list[LineString] = []
        for edge in self.internal_edges: 
            if edge.bend: 
                lines.append(LineString([edge.v[0].pos.toTuple(), edge.bend.toTuple()]))
                lines.append(LineString([edge.v[1].pos.toTuple(), edge.bend.toTuple()]))
            else: 
                lines.append(LineString([edge.v[0].pos.toTuple(), edge.v[1].pos.toTuple()]))

        buffered = [line.buffer(30, cap_style=1, join_style=1) for line in lines]
        geom = unary_union(buffered)

        shape_list = [geom]
        if geom.geom_type == "MultiPolygon":
            shape_list = geom.geoms
            
        for i, poly in enumerate(shape_list):
            shell = list(poly.exterior.coords)
            holes = [list(ring.coords) for ring in poly.interiors]
 
            border_part = [QPolygonF([QPointF(x, y) for x, y in shell])]
            for hole in holes: 
                border_part.append(QPolygonF([QPointF(x, y) for x, y in hole]))
            self.border.append(border_part)

    def determine_pivot_buttons(self): 
        self.pivot_buttons_pos = []
        dist_from_group = 150

        # to provent that the bounding box can't be a vertical or horizontal line 
        self.bounding_rect.setTop(self.bounding_rect.top() - 1)
        self.bounding_rect.setBottom(self.bounding_rect.bottom() + 1)
        self.bounding_rect.setLeft(self.bounding_rect.left() - 1)
        self.bounding_rect.setRight(self.bounding_rect.right() + 1)

        edges_rect = [
            QLineF(self.bounding_rect.topLeft(), self.bounding_rect.topRight()),
            QLineF(self.bounding_rect.topRight(), self.bounding_rect.bottomRight()),
            QLineF(self.bounding_rect.bottomRight(), self.bounding_rect.bottomLeft()),
            QLineF(self.bounding_rect.bottomLeft(), self.bounding_rect.topLeft()),
        ]

        for i, pivot_edge in enumerate(self.pivot_edges):
            
            line = QLineF(self.pivot_nodes[i].pos, pivot_edge.other(self.pivot_nodes[i]).pos)

            points = []
            
            for edge in edges_rect:
                edge_type, edge_point = edge.intersects(line)

                if edge_type == QLineF.IntersectionType.UnboundedIntersection:
                    if self.bounding_rect.contains(edge_point.x(), edge_point.y()): 
                        direction = QLineF(line.p1(), line.p2())
                        direction.setLength(1.0) 
                        points.append(edge_point + (direction.p2() - direction.p1()) * dist_from_group)
            if len(points) > 0: 
                self.pivot_buttons_pos.append(
                    max(points, 
                        key=lambda p: (p - self.pivot_nodes[i].pos).x()**2 + (p - self.pivot_nodes[i].pos).y()**2
                    )
                )
