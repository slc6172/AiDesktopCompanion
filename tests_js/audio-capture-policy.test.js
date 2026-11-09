const test = require('node:test');
const assert = require('node:assert/strict');
const { constraints, inspectSettings, acquire } = require('../static/audio-capture-policy.js');

test('requests verified AEC first and keeps noise controls best-effort', () => {
  const c = constraints(48000, true).audio;
  assert.deepEqual(c.echoCancellation, { exact: true });
  assert.deepEqual(c.noiseSuppression, { ideal: true });
  assert.deepEqual(c.autoGainControl, { ideal: true });
});

test('distinguishes verified, disabled and unknown AEC state', () => {
  assert.equal(inspectSettings({ echoCancellation: true }).mode, 'active');
  assert.equal(inspectSettings({ echoCancellation: false }).mode, 'disabled');
  assert.equal(inspectSettings({}).mode, 'unknown');
});

test('retries ideal AEC only after a constraint rejection and reports unknown state', async () => {
  const calls = [];
  const stream = { getAudioTracks: () => [{ getSettings: () => ({} ) }], getTracks: () => [{ stop() {} }] };
  const devices = { getUserMedia: async (c) => {
    calls.push(c);
    if (calls.length === 1) { const e = new Error('unsupported'); e.name = 'OverconstrainedError'; throw e; }
    return stream;
  } };
  const result = await acquire(devices, 44100);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].audio.echoCancellation, { exact: true });
  assert.deepEqual(calls[1].audio.echoCancellation, { ideal: true });
  assert.equal(result.status.mode, 'unknown');
});

test('rejects a stream that explicitly reports AEC disabled and stops its tracks', async () => {
  let stopped = false;
  const stream = { getAudioTracks: () => [{ getSettings: () => ({ echoCancellation: false }) }], getTracks: () => [{ stop() { stopped = true; } }] };
  const devices = { getUserMedia: async () => stream };
  await assert.rejects(acquire(devices, 48000), (e) => e.code === 'AEC_UNAVAILABLE');
  assert.equal(stopped, true);
});
