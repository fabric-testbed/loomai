from mergexp import *

net = Network('edgeids')

gw = net.node('gw', facility == 'moddeter')
edge = net.node('edge', facility == 'moddeter')
edge2 = net.node('edge2', facility == 'moddeter')
mon = net.node('mon', facility == 'moddeter')

link0 = net.connect([edge, edge2, gw])
link0[edge].socket.addrs = ip4('10.0.1.10/24')
link0[edge2].socket.addrs = ip4('10.0.1.11/24')
link0[gw].socket.addrs = ip4('10.0.1.1/24')
link1 = net.connect([gw, mon])
link1[gw].socket.addrs = ip4('10.0.2.1/24')
link1[mon].socket.addrs = ip4('10.0.2.10/24')

experiment(net)
