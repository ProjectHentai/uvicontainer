# Uvicontainer

### Ported from [uvicorn](https://github.com/encode/uvicorn), Aim to be a fast general TCP/UDP servcer

### example

```python
import asyncio

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
    uvicontainer.run("main:EchoServerProtocol", host="0.0.0.0", port=8000, workers=3, type="tcp")
```
- This starts a tcp server, like that in [python's document](https://docs.python.org/3/library/asyncio-protocol.html)