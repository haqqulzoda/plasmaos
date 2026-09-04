import net from 'node:net';

const listenPort = Number(process.argv[2]);
const targetPort = Number(process.argv[3]);
if (!Number.isInteger(listenPort) || !Number.isInteger(targetPort)) {
  throw new Error('usage: node cdp-port-forward.mjs <listen-port> <target-port>');
}

const server = net.createServer((client) => {
  const target = net.createConnection({host: '127.0.0.1', port: targetPort});
  client.pipe(target);
  target.pipe(client);
  const close = () => {
    client.destroy();
    target.destroy();
  };
  client.on('error', close);
  target.on('error', close);
});

server.listen(listenPort, '0.0.0.0');
