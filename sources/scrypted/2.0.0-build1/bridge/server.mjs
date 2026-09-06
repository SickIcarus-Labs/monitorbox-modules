import http from 'node:http';
import fs from 'node:fs';
import { connectScryptedClient } from '@scrypted/client';
import { ScryptedMimeTypes } from '@scrypted/types';
import { WebSocketServer } from 'ws';

const socketPath = process.env.SCRYPTED_BRIDGE_SOCKET || '/run/monitorbox-scrypted/bridge.sock';
const baseUrl = process.env.SCRYPTED_URL;
if (!baseUrl)
  throw new Error('SCRYPTED_URL is required');
const excludedNames = new Set(
  (process.env.SCRYPTED_EXCLUDED_CAMERA_NAMES || '')
    .split(',').map(value => value.trim()).filter(Boolean),
);
const operationTimeout = 15000;
let client;
let connecting;
let inventory = { connected: false, serverVersion: null, checkedAt: null, cameras: [], error: 'Starting' };
const activeProbes = new Map();
const probeQueue = [];
let probeWorkers = 0;
const liveSessions = new Set();
const maxLiveSessions = 4;

function log(message, fields = {}) {
  process.stdout.write(`${JSON.stringify({ time: new Date().toISOString(), message, ...fields })}\n`);
}

async function timed(label, promise, timeout = operationTimeout) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out`)), timeout); }),
    ]);
  }
  finally {
    clearTimeout(timer);
  }
}

async function connect() {
  if (client)
    return client;
  if (connecting)
    return connecting;
  connecting = (async () => {
    const normalLog = console.log;
    console.log = () => {};
    try {
      const value = await timed('Scrypted authentication', connectScryptedClient({
        baseUrl, pluginId: '@scrypted/core', username: process.env.SCRYPTED_USERNAME,
        password: process.env.SCRYPTED_PASSWORD, clientName: 'MonitorBox bridge', local: false,
      }));
      value.onClose = () => {
        client = undefined;
        inventory = { ...inventory, connected: false, error: 'Scrypted RPC connection closed' };
      };
      client = value;
      log('connected to Scrypted', { serverVersion: value.serverVersion });
      return value;
    }
    finally {
      console.log = normalLog;
      connecting = undefined;
    }
  })();
  return connecting;
}

function cleanProfile(profile) {
  return {
    id: String(profile.id), name: profile.name || String(profile.id), container: profile.container,
    destinations: profile.destinations || [],
    video: profile.video ? {
      codec: profile.video.codec, width: profile.video.width, height: profile.video.height,
      bitrate: profile.video.bitrate, fps: profile.video.fps,
    } : undefined,
    audio: profile.audio ? { codec: profile.audio.codec } : undefined,
  };
}

function selectProfile(profiles) {
  return profiles.find(profile => String(profile.id) === '1' && profile.video?.codec?.toLowerCase() === 'h264')
    || profiles.filter(profile => profile.video?.codec?.toLowerCase() === 'h264' && profile.video?.height <= 1080)
      .sort((a, b) => (b.video?.height || 0) - (a.video?.height || 0))[0]
    || profiles[0];
}

async function refreshInventory() {
  try {
    const sdk = await connect();
    const state = sdk.systemManager.getSystemState();
    const all = Object.keys(state).map(id => ({ id, device: sdk.systemManager.getDeviceById(id) }));
    const providers = Object.fromEntries(all.map(({ id, device }) => [id, {
      id, name: device?.name, pluginId: device?.pluginId,
    }]));
    const cameras = [];
    for (const { id, device } of all) {
      if (!['Camera', 'Doorbell'].includes(device?.type) || excludedNames.has(device?.name))
        continue;
      const profiles = device.interfaces?.includes('VideoCamera')
        ? await timed('stream profile read', device.getVideoStreamOptions(), 10000) : [];
      const selected = selectProfile(profiles);
      const online = device.online;
      cameras.push({
        id, name: device.name, type: device.type, nativeId: device.nativeId,
        pluginId: device.pluginId, providerId: device.providerId,
        provider: providers[device.providerId], interfaces: device.interfaces || [],
        online: online === true ? true : online === false ? false : null,
        onlineType: online === null ? 'null' : typeof online, profiles: profiles.map(cleanProfile),
        selectedProfileId: selected ? String(selected.id) : null,
      });
    }
    inventory = { connected: true, serverVersion: sdk.serverVersion,
      checkedAt: new Date().toISOString(), cameras, error: null };
    return inventory;
  }
  catch (error) {
    client?.disconnect();
    client = undefined;
    inventory = { ...inventory, connected: false, checkedAt: new Date().toISOString(),
      error: `${error.name}: ${error.message}`.slice(0, 300) };
    throw error;
  }
}

function approvedCamera(id) {
  const camera = inventory.cameras.find(item => item.id === id);
  if (!camera)
    throw Object.assign(new Error('unknown or excluded camera'), { statusCode: 404 });
  return camera;
}

async function mediaProbe(id, mode) {
  const key = `${id}:${mode}`;
  if (activeProbes.has(key))
    return activeProbes.get(key);
  const promise = new Promise((resolve, reject) => {
    probeQueue.push({ id, mode, resolve, reject });
    drainProbeQueue();
  }).finally(() => activeProbes.delete(key));
  activeProbes.set(key, promise);
  return promise;
}

function drainProbeQueue() {
  while (probeWorkers < 2 && probeQueue.length) {
    const item = probeQueue.shift();
    probeWorkers++;
    runMediaProbe(item.id, item.mode).then(item.resolve, item.reject).finally(() => {
      probeWorkers--;
      drainProbeQueue();
    });
  }
}

async function attempt(label, operation) {
  let first;
  for (let index = 0; index < 2; index++) {
    const started = performance.now();
    try {
      const value = await timed(label, operation());
      return { value, latencyMs: Math.round((performance.now() - started) * 10) / 10,
        attempts: index + 1 };
    }
    catch (error) {
      first = error;
      if (!index)
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
  throw first;
}

async function runMediaProbe(id, mode) {
  const sdk = await connect();
  if (!inventory.connected)
    await refreshInventory();
  const camera = approvedCamera(id);
  const device = sdk.systemManager.getDeviceById(id);
  if (!device)
    throw Object.assign(new Error('expected camera is missing'), { statusCode: 404 });
  const online = device.online;
  if (online === false)
    return { id, mode, online: false, state: 'offline', checkedAt: new Date().toISOString() };
  if (mode === 'snapshot') {
    const result = await attempt('snapshot', async () => {
      const picture = await device.takePicture();
      return sdk.mediaManager.convertMediaObjectToBuffer(picture, 'image/jpeg');
    });
    return { id, mode, online: online === true ? true : online === false ? false : null,
      state: 'healthy', checkedAt: new Date().toISOString(),
      bytes: result.value.length, latencyMs: result.latencyMs, attempts: result.attempts };
  }
  if (mode === 'stream') {
    const profile = camera.profiles.find(item => item.id === camera.selectedProfileId);
    const result = await attempt('stream acquisition', async () => {
      const stream = await device.getVideoStream({ id: camera.selectedProfileId });
      const value = await sdk.mediaManager.convertMediaObjectToBuffer(stream, ScryptedMimeTypes.FFmpegInput);
      const parsed = JSON.parse(value.toString());
      if (!Array.isArray(parsed.inputArguments) || !parsed.inputArguments.length)
        throw new Error('Scrypted returned no usable stream input');
      return parsed;
    });
    return { id, mode, online: online === true ? true : online === false ? false : null,
      state: 'healthy', checkedAt: new Date().toISOString(),
      latencyMs: result.latencyMs, attempts: result.attempts, profile };
  }
  throw Object.assign(new Error('unsupported probe mode'), { statusCode: 400 });
}

function json(response, status, value) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(status, { 'content-type': 'application/json', 'content-length': body.length,
    'cache-control': 'no-store' });
  response.end(body);
}

async function handler(request, response) {
  const url = new URL(request.url, 'http://localhost');
  try {
    if (request.method === 'GET' && url.pathname === '/v1/state') {
      if (!inventory.checkedAt || Date.now() - new Date(inventory.checkedAt).getTime() > 30000)
        await refreshInventory();
      return json(response, 200, { ...inventory, bridge: { activeLiveSessions: liveSessions.size,
        activeProbes: activeProbes.size, queuedProbes: probeQueue.length } });
    }
    const cameraState = url.pathname.match(/^\/v1\/cameras\/([^/]+)\/state$/);
    if (request.method === 'GET' && cameraState) {
      const id = decodeURIComponent(cameraState[1]);
      const camera = approvedCamera(id);
      const sdk = await connect();
      const device = sdk.systemManager.getDeviceById(id);
      if (!device)
        throw Object.assign(new Error('expected camera is missing'), { statusCode: 404 });
      const online = device.online;
      return json(response, 200, { ...camera,
        online: online === true ? true : online === false ? false : null,
        onlineType: online === null ? 'null' : typeof online,
      });
    }
    const snapshot = url.pathname.match(/^\/v1\/cameras\/([^/]+)\/snapshot$/);
    if (request.method === 'GET' && snapshot) {
      const id = decodeURIComponent(snapshot[1]);
      approvedCamera(id);
      const sdk = await connect();
      const device = sdk.systemManager.getDeviceById(id);
      const result = await attempt('snapshot', async () => {
        const picture = await device.takePicture();
        return sdk.mediaManager.convertMediaObjectToBuffer(picture, 'image/jpeg');
      });
      response.writeHead(200, { 'content-type': 'image/jpeg', 'content-length': result.value.length,
        'cache-control': 'no-store' });
      return response.end(result.value);
    }
    const probe = url.pathname.match(/^\/v1\/cameras\/([^/]+)\/probe$/);
    if (request.method === 'POST' && probe) {
      const mode = url.searchParams.get('mode');
      return json(response, 200, await mediaProbe(decodeURIComponent(probe[1]), mode));
    }
    json(response, 404, { error: 'not found' });
  }
  catch (error) {
    log('request failed', { path: url.pathname, error: `${error.name}: ${error.message}`.slice(0, 300) });
    json(response, error.statusCode || 503, { error: error.message?.slice(0, 300) || 'request failed',
      kind: inventory.connected ? 'camera_probe' : 'scrypted_unavailable' });
  }
}

function startBrowserLiveSession(socket, id) {
  if (liveSessions.size >= maxLiveSessions) {
    socket.close(1013, 'live session limit reached');
    return;
  }
  liveSessions.add(socket);
  const pending = new Map();
  const candidateSenders = new Map();
  let sequence = 0;
  let control;
  let closed = false;
  let setupTimer;
  let lifetimeTimer;

  const close = async (code = 1000, reason = 'session ended') => {
    if (closed)
      return;
    closed = true;
    clearTimeout(setupTimer);
    clearTimeout(lifetimeTimer);
    liveSessions.delete(socket);
    for (const value of pending.values())
      value.reject(new Error(reason));
    pending.clear();
    candidateSenders.clear();
    try { await control?.endSession(); } catch {}
    try { socket.close(code, reason); } catch {}
  };

  const callBrowser = (method, args = [], candidateSender) => new Promise((resolve, reject) => {
    if (closed || socket.readyState !== socket.OPEN)
      return reject(new Error('browser playback session closed'));
    const callId = String(++sequence);
    pending.set(callId, { resolve, reject });
    if (candidateSender)
      candidateSenders.set(callId, candidateSender);
    socket.send(JSON.stringify({ type: 'call', callId, method, args, trickle: Boolean(candidateSender) }));
  });

  socket.once('message', async data => {
    try {
      const hello = JSON.parse(data.toString());
      if (hello.type !== 'hello' || !hello.options)
        throw new Error('invalid live session handshake');
      const sdk = await connect();
      if (!inventory.connected)
        await refreshInventory();
      approvedCamera(id);
      const device = sdk.systemManager.getDeviceById(id);
      if (!device?.interfaces?.includes('RTCSignalingChannel'))
        throw new Error('camera has no Scrypted WebRTC signaling channel');
      const session = {
        __json_disable_serialization: true,
        __proxy_props: { options: hello.options },
        options: hello.options,
        getOptions: async () => hello.options,
        createLocalDescription: (type, setup, sendIceCandidate) =>
          callBrowser('createLocalDescription', [type, setup], sendIceCandidate),
        setRemoteDescription: (description, setup) =>
          callBrowser('setRemoteDescription', [description, setup]),
        addIceCandidate: candidate => callBrowser('addIceCandidate', [candidate]),
      };
      control = await timed('WebRTC signaling setup', device.startRTCSignalingSession(session), 30000);
      if (closed) {
        try { await control?.endSession(); } catch {}
        return;
      }
      clearTimeout(setupTimer);
      socket.send(JSON.stringify({ type: 'ready' }));
      lifetimeTimer = setTimeout(() => close(1000, 'session time limit reached'), 10 * 60 * 1000);
    }
    catch (error) {
      log('live session setup failed', { cameraId: id, error: `${error.name}: ${error.message}`.slice(0, 300) });
      try { socket.send(JSON.stringify({ type: 'error', error: error.message?.slice(0, 200) || 'setup failed' })); } catch {}
      await close(1011, 'playback setup failed');
    }
  });

  socket.on('message', async data => {
    let message;
    try { message = JSON.parse(data.toString()); } catch { return; }
    if (message.type === 'result') {
      const waiter = pending.get(String(message.callId));
      if (!waiter)
        return;
      pending.delete(String(message.callId));
      if (message.error)
        waiter.reject(new Error(String(message.error).slice(0, 200)));
      else
        waiter.resolve(message.value);
    }
    else if (message.type === 'candidate') {
      const sender = candidateSenders.get(String(message.callId));
      if (sender)
        await sender(message.candidate).catch(() => {});
    }
  });
  socket.on('close', () => close());
  socket.on('error', () => close(1011, 'browser socket error'));
  setupTimer = setTimeout(() => close(1008, 'handshake timed out'), 10000);
}

try { fs.unlinkSync(socketPath); } catch (error) { if (error.code !== 'ENOENT') throw error; }
const server = http.createServer(handler);
const webSockets = new WebSocketServer({ noServer: true, maxPayload: 1024 * 1024 });
server.on('upgrade', (request, socket, head) => {
  const url = new URL(request.url, 'http://localhost');
  const match = url.pathname.match(/^\/v1\/cameras\/([^/]+)\/live$/);
  if (!match) {
    socket.destroy();
    return;
  }
  const id = decodeURIComponent(match[1]);
  try { approvedCamera(id); }
  catch { socket.destroy(); return; }
  webSockets.handleUpgrade(request, socket, head, ws => startBrowserLiveSession(ws, id));
});
server.listen(socketPath, () => {
  fs.chmodSync(socketPath, 0o660);
  log('bridge ready', { socketPath });
  refreshInventory().catch(error => log('initial inventory failed', { error: error.message }));
});
const timer = setInterval(() => refreshInventory().catch(() => {}), 60000);

async function shutdown() {
  clearInterval(timer);
  for (const socket of liveSessions)
    socket.close(1001, 'bridge stopping');
  server.close();
  client?.disconnect();
  try { fs.unlinkSync(socketPath); } catch {}
  setTimeout(() => process.exit(0), 50);
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
