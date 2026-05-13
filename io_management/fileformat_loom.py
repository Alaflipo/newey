import json

from elements.network import Network, Node, Edge

from PySide6.QtCore import QPointF

def read_network_from_loom(filename):
    network = Network(file_path=filename)
    with open(filename) as fp:
        edge_staging = [] # don't resolve edges until we have all the nodes
        data = json.load(fp)
        assert data['type'] == "FeatureCollection"
        for feat in data['features']:
            geom = feat['geometry']
            if geom['type']=="Point":
                prop = feat['properties']
                name = prop['id'] # station_id ?
                label = prop.get('station_label','')
                assert isinstance(name,str)
                assert isinstance(label,str)
                x, y = geom['coordinates']
                network.nodes[name] = Node( x, -y, name, label )
            elif geom['type']=="LineString":
                prop = feat['properties']
                s = prop['from']
                t = prop['to']
                id = prop['lines'][0]['id']
                color = [prop['lines'][i]['color'] for i in range(len(prop['lines']))]
                # if len(prop['lines'])==1:
                #     color = prop['lines'][0]['color']
                # else:
                #     color = '000000'
                edge_staging.append( (s,t,color,id) )
        
        # first_node = list(network.nodes.values())[0]
        # for i in range(20): 
        #     next_pos = first_node.pos + QPointF(-0.01, 0)
        #     network.nodes[f'test{i}'] = Node(next_pos.x(), next_pos.y(), f'test{i}', f'test{i}')
        #     edge_staging.append((first_node.name, f'test{i}', '000000'))
        #     first_node = network.nodes[f'test{i}']

        metro_lines: dict[str, list[Edge]] = {}

        for s,t,color,id in edge_staging:
            s = network.nodes[s]
            assert isinstance(s, Node)
            t = network.nodes[t]
            assert isinstance(t, Node)
            e = add_edge(s,t)
            e.color = color
            e.line_id = id
            network.edges.append( e )

            # Add metro lines 
            if id in metro_lines: 
                metro_lines[id].append(e)
            else: 
                metro_lines[id] = [e]
        
        network.metro_lines = metro_lines
    return network, data

def example_network(): 
    network = Network()
    nodes = [Node( 5, -2, 'test1', 'test1' ), Node( 3, -4, 'test2', 'test2' ), Node( 5, -6, 'test3', 'test3' ), Node( 7, -4, 'test4', 'test4' )]
    for node in nodes: 
        network.nodes[node.name] = node 
    for i in range(len(nodes)): 
        edge = add_edge(nodes[i], nodes[(i+1)%len(nodes)])
        network.edges.append(edge)
    network.nodes['test5'] = Node(10, -4, 'test5', 'test5')
    network.edges.append(add_edge(network.nodes['test5'], network.nodes['test4']))
    return network

def empty_network(): 
    network = Network()
    nodes = [Node( 5, -2, 'Middle', 'Middle' ), Node( 3, -4, 'Paroni', 'Paroni' )]
    for node in nodes: 
        network.nodes[node.name] = node 
    edge = add_edge(nodes[0], nodes[1])
    network.edges.append(edge)
    return network

def add_edge(s,t):
    e = Edge(s,t)

    s.edges.append(e)
    t.edges.append(e)
    return e

def export_loom( net: Network, data ):
    # Put the layout from the Network into Loom's filedata,
    # so that when we run loom on it, it has our positions and bends.
    
    scale = 2e-5 # Scale the coordinates to play nice with Loom's assumptions
    for feat in data['features']:
        geom = feat['geometry']
        if geom['type']=="Point":
            prop = feat['properties']
            name = prop['id']
            v = net.nodes[name]
            geom['coordinates'] = [scale*v.pos.x(), -scale*v.pos.y() ]
        if geom['type']=="LineString":
            prop = feat['properties']
            s = net.nodes[ prop['from'] ]
            t = net.nodes[ prop['to'] ]
            geom = feat['geometry']
            bend = []
            for e in s.edges:
                if e.v[0]==t or e.v[1]==t:
                    if e.bend:
                        bend = [[scale*e.bend.x(),-scale*e.bend.y()]]
                        break
            geom['coordinates'] = [[scale*s.pos.x(),-scale*s.pos.y()]]+bend+[[scale*t.pos.x(),-scale*t.pos.y()]]

    with open('render.json','w') as fp:
        json.dump(data,fp)

def render_loom( fname_in, fname_out ):
    import subprocess
    cmd = f"cat {fname_in} | loom | transitmap -l > {fname_out}"
    subprocess.Popen(cmd,shell=True)
