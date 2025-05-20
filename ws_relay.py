""" WebSocket Relay Server """

import asyncio
import websockets

connected_clients = set()


async def handler(websocket):
    """ Handle incoming WebSocket connections """
    print(f"Client connected: {websocket.remote_address}")
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            print(f"Received: {message}")
            await asyncio.gather(*[
                client.send(message)
                for client in connected_clients
                if client != websocket
            ])
    except websockets.exceptions.ConnectionClosed:
        print(f"Client disconnected: {websocket.remote_address}")
    finally:
        connected_clients.remove(websocket)


async def main():
    """ Main function to start the WebSocket server """
    async with websockets.serve(handler, "0.0.0.0", 8000):
        print("WebSocket relay server running on ws://0.0.0.0:8000")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
