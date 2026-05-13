from math import pi
from time import perf_counter

from elements.network import *

from elements.group import Group

### GEOGRAPHIC COST CALCULATIONS ###

import numpy as np

def angle_error( a, b ):
    diff = abs(a-b) % (2*pi)
    return min(diff, 2*pi-diff)

def cost_matrix( v: Node):
    port_angles = [ i*(pi/4) for i in range(8) ]
    edge_angles = [ e.geo_angle(v) for e in v.edges ]
    return np.matrix( [ [ angle_error(pa,ea)**2 for pa in port_angles ] for ea in edge_angles ] )

# Two things to check for: 
# - We give priority to labels that are horizontal so 0 and 4 and don't want 2 and 6 and for the odd numbers they should be equal
# - We want labels that are on the outside to appear on the outside (either do this by a weighted middle point of the network or check whether labels point towards the outer face instead of an inner face)
def cost_matrix_labels(v: Node, mid_point_x): 
    port_angles = [ i*(pi/4) for i in range(8) ]
    edge_angles = []
    for i,e in enumerate(v.edges): 
        if v.locked: 
            edge_angles.append(port_angles[v.edges[i].port_at(v)])
        else: 
            edge_angles.append(e.geo_angle(v))
    # edge_angles = [ e.geo_angle(v) for e in v.edges ]
    port_edge_matrix = np.matrix( [ [ angle_error(pa,ea)**2 for pa in port_angles ] for ea in edge_angles ] )
    wl = [0.01 * v.label_hor, 0.02 * v.label_hor, 0.03 * v.label_hor]

    ### Based on lines add weights for labels 

    ### This is now commented out because of the feature (when dragging nodes are locked in place, but still the label positions I want to have fixed in place)
    # if the node is locked we want to choose the port of the old label 
    # if old_node.locked: 
    #     label_weights = [1 for i in range(8)]
    #     label_weights[old_node.label_node.port] = 0 
    #     return np.vstack([port_edge_matrix, label_weights])

    if len(v.edges) <= 2: 
        return left_wm(port_edge_matrix, wl) if v.left_line else right_wm(port_edge_matrix, wl)
    else : 
        return left_wm(port_edge_matrix, wl) if v.geo_pos.x() <= mid_point_x else right_wm(port_edge_matrix, wl)

    ### OLD
    # if v.geo_pos.x() <= mid_point_x: 
    #     return np.vstack([port_edge_matrix, np.array([wl[0] / 2, wl[1] /2 , wl[2], wl[1], wl[0], wl[1], wl[2], wl[1] / 2])])
    # else: 
    #     return np.vstack([port_edge_matrix, np.array([wl[0], wl[1], wl[2], wl[1] / 2, wl[0] / 2, wl[1] /2 , wl[2], wl[1]])])

# Left weighted matrix 
def left_wm(port_edge_matrix, wl): 
    return np.vstack([port_edge_matrix, np.array([wl[0] / 2, wl[1] /2 , wl[2], wl[1], wl[0], wl[1], wl[2], wl[1] / 2])])

# Right weighted matrix 
def right_wm(port_edge_matrix, wl): 
    return np.vstack([port_edge_matrix, np.array([wl[0], wl[1], wl[2], wl[1] / 2, wl[0] / 2, wl[1] /2 , wl[2], wl[1]])])

def normal_wm(port_edge_matrix, wl): 
    return np.vstack([port_edge_matrix, np.array([wl[0], wl[1], wl[2], wl[1], wl[0], wl[1] , wl[2], wl[1]])])

### ROUNDING ###

def assign_by_rounding( net: Network ):
    # the way it is implemented now, we can mess up the rotation system unnecessarily
    net.evict_all_labels()
    net.evict_all_edges()
    for v in net.nodes.values():
        for e in v.edges:
            port = round_angle_to_port(e.geo_angle(v))
            v.assign( e, port, force=False )
        v.assign_label(v.first_free_port())


### MATCHING ###

from scipy.optimize import linear_sum_assignment

def assign_by_local_matching( net: Network ):
    all_costs = []
    for vi, v in enumerate(net.nodes.values()):
        # Cost matrix for labels
        all_costs.append(cost_matrix_labels(v, net.midpoint.x()))

    net.evict_all_labels()
    net.evict_all_edges()
    for vi, v in enumerate(net.nodes.values()):
        _, cols = linear_sum_assignment(all_costs[vi])
        for i,p in enumerate(cols[:-1]):
            v.assign( v.edges[int(i)], int(p) )

        # Assign the correct label 
        v.assign_label(int(cols[-1]))

### INTEGER LINEAR PROGRAMMING ###

### For the labeling I want a few things: 
### - Labels should appear on the same side of a line 

from ortools.linear_solver import pywraplp as lp
def assign_by_ilp( net: Network):
    # bend cost is relative to squared angle errors

    solver: lp.Solver = lp.Solver.CreateSolver("SCIP")
    start = perf_counter()
    objective = solver.Sum([])
    portvars = dict()
    portvars_labels = dict()
    for vi, v in enumerate(net.nodes.values()):
        costs = cost_matrix_labels(v, net.midpoint.x())
        for i,e in enumerate(v.edges):
            my_portvars = [solver.BoolVar(f'pass_{v.name}_{i}_{p}') for p in range(8)]
            for p in range(8):
                objective += costs[i,p] * my_portvars[p]
            # pick exactly one port for an edge
            solver.Add( solver.Sum(my_portvars)==1 )
            portvars[(v,e)] = my_portvars
        
        #### For labeling ####
        portvars_label = [solver.BoolVar(f'label_{v.name}_{p}') for p in range(8)]
        for p in range(8):
            objective += costs[len(costs)-1,p] * portvars_label[p]
        # Pick one port for each label 
        solver.Add( solver.Sum(portvars_label)==1 )
        portvars_labels[v] = portvars_label

        for p in range(8):
            # assign at most one (edge or LABEL) to a port
            solver.Add( solver.Sum([ portvars[(v,e)][p] for e in v.edges ] + [portvars_label[p]]) <= 1 )

    # consistent port assignment by identifying opposite sides of the same edge
    for e in net.edges:
        for p in range(8):
            solver.Add( portvars[(e.v[0],e)][p] == portvars[(e.v[1],e)][opposite_port(p)] )

    # bend penalty
    for v in net.nodes.values():
        if len(v.edges)==2:
            penalty = solver.BoolVar(f'bend_{v.name}')
            objective += v.bend_penalty*penalty
            e = v.edges[0]
            f = v.edges[1]
            for p in range(8):
                solver.Add( penalty >= portvars[(v,e)][p] - portvars[(v,f)][opposite_port(p)])

    # labels on the same degree 2 line should be on the same side 
    for line in net.deg_2_lines: 
        if len(net.nodes[line[0]].edges) > 2: line.pop(0)
        if len(net.nodes[line[len(line) - 1]].edges) > 2: line.pop(len(line) - 1)
        for p in range(8): 
            for a_name, b_name in zip(line, line[1:]): 
                a, b = net.nodes[a_name], net.nodes[b_name]
                penalty_strength = max(a.label_same_side, b.label_same_side)
                penalty = solver.BoolVar(f'label_{a_name}_{b_name}')
                objective += penalty_strength * penalty
                solver.Add( penalty >= portvars_labels[a][p] - portvars_labels[b][p])
                # solver.Add( penalty <= portvars_labels[a][p] - portvars_labels[b][p])

    # # Labels on the same side
    # seen = dict()
    # for v in list(net.nodes.values()):
    #     if v.name in seen: continue
    #     if is_deg2(v):
    #         seen[v.name] = True
    #         path1 = spacewalk( v.edges[0].other(v), v, seen )
    #         path2 = spacewalk( v.edges[1].other(v), v, seen )
    #         walk = path1 + [v] + [v for v in reversed(path2)]
    #         print([node.label for node in walk])
    #         for a, b in zip(walk,walk[1:]): 
    #             print(a.label, b.label)
    #         # label same side 
    #         for p in range(8): 
    #             for a, b in zip(walk,walk[1:]):
    #                 if a == b: continue 
    #                 penalty = solver.BoolVar(f'label_{a.name}_{b.name}')
    #                 objective += label_side_strength/10 * penalty
    #                 solver.Add( penalty >= portvars_labels[a][p] - portvars_labels[b][p])
    #                 # solver.Add( penalty <= portvars_labels[a][p] - portvars_labels[b][p])

    solver.Minimize(objective)
    status = solver.Solve()
    runtime = perf_counter()-start
    print( "pa-ilp\tPort assignment ILP runtime (s)\t" + str(runtime) )
    print( 'Port assignment ILP runtime', runtime, 's' )
    print( 'Solver status', status )
    if status==0:
        net.evict_all_labels()
        net.evict_all_edges()
        for (v,e), x in portvars.items():
            for p in range(8):
                if x[p].solution_value()>0.5:
                    v.assign(e,p)

        # brute force simple port assignment
        for v, x in portvars_labels.items(): 
            for p in range(8): 
                if x[p].solution_value() > 0.5: 
                    v.assign_label(p)
                    v.label_node.set_pos_by_port(p)
        # for v in net.nodes.values(): 
        #     v.assign_label(v.first_free_port())
    else:
        print( 'Port assignment ILP infeasible' )
        print( "stats\tPort assignment ILP infeasible" )

def is_deg2(v: Node):
    return len(v.edges)==2

def spacewalk( v: Node, prev, seen ):
    seen[v.name] = True
    walk = []
    if is_deg2(v):
        v0 = v.edges[0].other(v)
        v1 = v.edges[1].other(v)
        next = v0 if v1==prev else v1
        if not next.name in seen:
            walk = spacewalk( next, v, seen )
    walk.append(v)
    return walk

def post_fix_overlap_ilp_new(net: Network, label_dist):
    
    solver: lp.Solver = lp.Solver.CreateSolver("SCIP")

    start_1 = perf_counter()
    objective = solver.Sum([])
    portvars_labels: dict[Node, dict[int, any]] = dict()

    for vi, v in enumerate(net.nodes.values()):
        costs = cost_matrix_labels(v, net.midpoint.x())

        #### For labeling ####
        free_ports = v.get_free_ports()
        possible_ports = free_ports + [v.label_node.port]
        
        # portvars_label is a dictionairy with the portnumber as key and the boolvar as value
        portvars_label: dict[int, any] = {}
        for p in possible_ports: 
            portvars_label[p] = solver.BoolVar(f'label_{v.name}_{p}')
        
        for p in possible_ports:
            objective += costs[len(costs)-1,p] * portvars_label[p]

        # Pick one port for each label 
        solver.Add( solver.Sum(portvars_label.values())==1 )
        portvars_labels[v] = portvars_label   

        # Penalty if we choose a different port then previously assigned 
        for port, port_var in portvars_label.items():
            if port == v.label_node.port: continue 
            penalty = solver.BoolVar(f'different_label_{v.name}_{port}')
            objective += penalty
            solver.Add( penalty >= port_var)

    # pre-calculation of label rectangles (speeds up the process!!)
    rects: dict[Node, dict[int, QPolygonF]] = {}
    for v in net.nodes.values(): 
        rects[v] = {}
        for p in portvars_labels[v]:
            rects[v][p] = v.label_node.get_rectangle_port(p, label_dist=label_dist)
    
    # Express that when two labels will overlap in a particular configuration, that it is impossible to get that configuration
    for v1 in net.nodes.values(): 
        # loop trough they keys of the dictionariy which are port integers 
        for p_v1 in portvars_labels[v1]:

            rect_self = rects[v1][p_v1]

            # Check overlap with edges 
            if net.edges_overlaps_label(rect_self): 
                solver.Add(portvars_labels[v1][p_v1] == 0)
                continue 

            # Check overlap with other labels 
            for v2 in net.nodes.values(): 
                if v1.name == v2.name: continue 
                # loop trough they keys of the dictionariy which are port integers
                for p_v2 in portvars_labels[v2]:
                    rect_other = rects[v2][p_v2]
                    if rect_self.intersects(rect_other):
                        solver.Add(portvars_labels[v1][p_v1] + portvars_labels[v2][p_v2] <= 1)

    for line in net.deg_2_lines: 
        if len(net.nodes[line[0]].edges) > 2: line.pop(0)
        if len(net.nodes[line[len(line) - 1]].edges) > 2: line.pop(len(line) - 1)
        for p in range(8): 
            for a_name, b_name in zip(line, line[1:]): 
                a, b = net.nodes[a_name], net.nodes[b_name]
                penalty_strength = max(a.label_same_side, b.label_same_side)
                penalty = solver.BoolVar(f'label_{a.name}_{b.name}')
                objective += penalty_strength * penalty
                if p in portvars_labels[a].keys() and p in portvars_labels[b].keys(): 
                    solver.Add( penalty >= portvars_labels[a][p] - portvars_labels[b][p])
        
        # needed to express that when keys are missing (aka label placement is impossible we also get a penalty)
        # for a_name in line: 
        #     for b_name in line: 
        #         if a_name == b_name: continue 
        #         a, b = net.nodes[a_name], net.nodes[b_name]
        #         for p in portvars_labels[a].keys():
        #             if p not in portvars_labels[b].keys(): 
        #                 penalty_strength = max(a.label_same_side, b.label_same_side)
        #                 penalty = solver.BoolVar(f'label_imp_{a.name}_{b.name}')
        #                 objective += penalty_strength * penalty
        #                 solver.Add( penalty >= portvars_labels[a][p])
    
    start_2 = perf_counter()
    runtime_p1 = start_2-start_1
    print( "plf-calc\t Post-Label overlap fix pre-processing runtime\t" + str(runtime_p1) )
    
    solver.Minimize(objective)
    status = solver.Solve()
    runtime_p2 = perf_counter()-start_2
    total_runtime = perf_counter()-start_1
    print( "plf-ilp\t Post-Label overlap fix ILP runtime (s)\t" + str(runtime_p2) )
    print( 'Post-Label overlap fix ILP runtime', total_runtime, 's' )
    print( 'Solver status', status )
    if status==0:
        for v, port_vars in portvars_labels.items(): 
            for p, port_var in port_vars.items():
                if port_var.solution_value() > 0.5 and p != v.label_node.port: 
                    v.evict_label()
                    v.assign_label(p)
        return True 
    else:
        print( 'Port assignment ILP infeasible' )
        print( "stats\tPort assignment ILP infeasible" )
        return False

def post_fix_overlap_ilp_group(net: Network, label_dist, group: Group):
    
    solver: lp.Solver = lp.Solver.CreateSolver("SCIP")

    start_1 = perf_counter()
    objective = solver.Sum([])
    portvars_labels: dict[Node, dict[int, any]] = dict()

    for vi, v in enumerate(group.nodes):
        costs = cost_matrix_labels(v, net.midpoint.x())

        #### For labeling ####
        free_ports = v.get_free_ports()
        possible_ports = free_ports + [v.label_node.port]
        
        # portvars_label is a dictionairy with the portnumber as key and the boolvar as value
        portvars_label: dict[int, any] = {}
        for p in possible_ports: 
            portvars_label[p] = solver.BoolVar(f'label_{v.name}_{p}')
        
        for p in possible_ports:
            objective += costs[len(costs)-1,p] * portvars_label[p]

        # Pick one port for each label 
        solver.Add( solver.Sum(portvars_label.values())==1 )
        portvars_labels[v] = portvars_label   

        # Penalty if we choose a different port then previously assigned 
        # for port, port_var in portvars_label.items():
        #     if port == v.label_node.port: continue 
        #     penalty = solver.BoolVar(f'different_label_{v.name}_{port}')
        #     objective += penalty
        #     solver.Add( penalty >= port_var)

    # pre-calculation of label rectangles (speeds up the process!!)
    rects: dict[Node, dict[int, QPolygonF]] = {}
    for v in group.nodes: 
        rects[v] = {}
        for p in portvars_labels[v]:
            rects[v][p] = v.label_node.get_rectangle_port(p, label_dist=label_dist)
    other_rects: list[QPolygonF] = [v.label_node.rectangle_points for v in net.nodes.values() if v not in group.nodes]
    
    # Express that when two labels will overlap in a particular configuration, that it is impossible to get that configuration
    for v1 in group.nodes: 
        # loop trough they keys of the dictionariy which are port integers 
        for p_v1 in portvars_labels[v1]:

            rect_self = rects[v1][p_v1]

            # Check overlap with edges 
            if net.edges_overlaps_label(rect_self): 
                solver.Add(portvars_labels[v1][p_v1] == 0)
                continue 

            # Check overlap with other labels 
            for v2 in group.nodes: 
                if v1.name == v2.name: continue 
                # loop trough they keys of the dictionariy which are port integers
                for p_v2 in portvars_labels[v2]:
                    rect_other = rects[v2][p_v2]
                    if rect_self.intersects(rect_other):
                        solver.Add(portvars_labels[v1][p_v1] + portvars_labels[v2][p_v2] <= 1)

            # There should be no overlap with any other label in the network 
            for rect in other_rects: 
                if rect_self.intersects(rect): 
                    solver.Add(portvars_labels[v1][p_v1] <= 0)

    for line in group.deg_2_lines: 
        if len(line[0].edges) > 2: line.pop(0)
        if len(line[len(line) - 1].edges) > 2: line.pop(len(line) - 1)
        for p in range(8): 
            for a, b in zip(line, line[1:]): 
                penalty_strength = max(a.label_same_side, b.label_same_side)
                penalty = solver.BoolVar(f'label_{a.name}_{b.name}')
                objective += penalty_strength * penalty
                if p in portvars_labels[a].keys() and p in portvars_labels[b].keys(): 
                    solver.Add( penalty >= portvars_labels[a][p] - portvars_labels[b][p])

        # needed to express that when keys are missing (aka label placement is impossible we also get a penalty)
        # for a in line: 
        #     for b in line: 
        #         if a == b: continue 
        #         for p in portvars_labels[a].keys():
        #             if p not in portvars_labels[b].keys(): 
        #                 penalty_strength = max(a.label_same_side, b.label_same_side) / 10
        #                 penalty = solver.BoolVar(f'label_imp_{a.name}_{b.name}')
        #                 objective += penalty_strength * penalty
        #                 solver.Add( penalty >= portvars_labels[a][p])
                    
    
    start_2 = perf_counter()
    runtime_p1 = start_2-start_1
    print( "plf-calc\t Post-Label overlap fix pre-processing runtime\t" + str(runtime_p1) )
    
    solver.Minimize(objective)
    status = solver.Solve()
    runtime_p2 = perf_counter()-start_2
    total_runtime = perf_counter()-start_1
    print( "plf-ilp\t Post-Label overlap fix ILP runtime (s)\t" + str(runtime_p2) )
    print( 'Post-Label overlap fix ILP runtime', total_runtime, 's' )
    print( 'Solver status', status )
    if status==0:
        for v, port_vars in portvars_labels.items(): 
            for p, port_var in port_vars.items():
                if port_var.solution_value() > 0.5 and p != v.label_node.port: 
                    v.evict_label()
                    v.assign_label(p)
    else:
        print( 'Port assignment ILP infeasible' )
        print( "stats\tPort assignment ILP infeasible" )

def post_fix_overlap_ilp_old(net: Network, label_dist): 

    overlaps = net.check_label_overlaps()

    solver: lp.Solver = lp.Solver.CreateSolver("SCIP")
    start = perf_counter()
    objective = solver.Sum([])
    portvars_labels = dict()

    for vi, v in enumerate(net.nodes.values()):
        costs = cost_matrix_labels(v, net.midpoint.x())

        free_ports = v.get_free_ports() + [v.label_node.port]
        
        #### For labeling ####
        portvars_label = [solver.BoolVar(f'label_{v.name}_{p}') for p in free_ports]
        for i, p in enumerate(free_ports):
            objective += costs[len(costs)-1,p] * portvars_label[i]
        # Pick one port for each label 
        solver.Add( solver.Sum(portvars_label)==1 )
        portvars_labels[v] = portvars_label   

        # Penalty if we choose a different port then previously assigned 
        for i in range(len(free_ports[:-1])):
            penalty = solver.BoolVar(f'label_{v.name}_{free_ports[i]}')
            objective += penalty
            solver.Add( penalty >= portvars_labels[v][i])
    
    # make sure that overlaps don't have the same port 
    for overlap in overlaps: 
        # they can't both stay the same 
        if len(overlap) == 2: 
            v1 = overlap[0]
            v2 = overlap[1]
            solver.Add( portvars_labels[v1][len(portvars_labels[v1]) - 1] + portvars_labels[v2][len(portvars_labels[v2]) - 1] <= 1)
        
        # bigger penalty if we stay on the edge overlap 
        if len(overlap) == 1: 
            v = overlap[0]
            penalty = solver.BoolVar(f'edge_overlap_{v.name}_{free_ports[i]}')
            objective += 10 * penalty
            solver.Add( penalty >= portvars_labels[v][len(portvars_labels[v]) - 1])
        
        # We also add a penalty if the newly chosen spot will also be an overlap
        for v in overlap: 
            for i, port in enumerate(v.get_free_ports()): 
                rect = v.label_node.get_rectangle_port(port, label_dist)
                if net.overlaps_with_label(rect): 
                    print(f'new_overlap_{v.label}_{port}')
                    penalty = solver.BoolVar(f'new_overlap_{v.name}_{port}')
                    objective += 10 * penalty
                    solver.Add( penalty >= portvars_labels[v][i])
    
    ##### NOTE: For each vertex in which there is currently overlap with either edge or other label need to compare every configuration that is possible between them all.  ###
    


    # for overlap in overlaps: 
    #     v = overlap[0]
    #     p_candidates = []
    #     for p in v.get_free_ports(): 
    #         rect_to_check = v.label_node.get_rectangle_port(p, label_dist=label_dist)
    #         if not net.overlaps_with_label(rect_to_check): 
    #             p_candidates.append(p)
    #     candidates = [solver.BoolVar(f'label_{v.name}_{p}') for p in p_candidates]
    #     candidates()

    solver.Minimize(objective)
    status = solver.Solve()
    runtime = perf_counter()-start
    print( "pa-ilp\tPort assignment ILP runtime (s)\t" + str(runtime) )
    print( 'Port assignment ILP runtime', runtime, 's' )
    print( 'Solver status', status )
    if status==0:
        for v, x in portvars_labels.items(): 
            free_ports = v.get_free_ports() + [v.label_node.port]
            for i, p in enumerate(free_ports): 
                if x[i].solution_value() > 0.5: 
                    v.evict_label()
                    v.assign_label(p)
    else:
        print( 'Port assignment ILP infeasible' )
        print( "stats\tPort assignment ILP infeasible" )

def get_possible_ports(net: Network, label_dist: int) -> list[list[int]]:
    free_ports_mat = []
    for v in net.nodes.values():
        free_ports = []
        for p in v.get_free_ports(): 
            rect_to_check = v.label_node.get_rectangle_port(p, label_dist=label_dist)
            if not net.overlaps_with_label(rect_to_check): 
                free_ports.append(p)
        free_ports.append(v.label_node.port)
        free_ports_mat.append(free_ports)
    return free_ports_mat
