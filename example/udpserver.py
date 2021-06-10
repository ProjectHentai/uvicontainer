import asyncio
import sys
sys.path.append("../")
import uvicontainer


class EchoServerProtocol:
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        message = data.decode()
        print('Received %r from %s' % (message, addr))
        print('Send %r to %s' % (message, addr))
        self.transport.sendto(data, addr)


if __name__ == "__main__":
    uvicontainer.run("udpserver:EchoServerProtocol", type="udp", host="0.0.0.0", port=8000, workers=3)
