# -*- coding: utf-8 -*-
import asyncio
import sys
sys.path.append("../")
import uvicontainer


class EchoServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        print('Connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, data):
        message = data.decode()
        print('Data received: {!r}'.format(message))

        print('Send: {!r}'.format(message))
        self.transport.write(data)

        print('Close the client socket')
        self.transport.close()


if __name__ == "__main__":
    uvicontainer.run("sigleprocessprotocol:EchoServerProtocol", host="0.0.0.0", port=8000, workers=3)
