const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function loadWorklet(rate = 48000) {
  let Processor;
  const context = {
    sampleRate: rate,
    currentFrame: 0,
    AudioWorkletProcessor: class {
      constructor() {
        this.messages = [];
        this.port = { postMessage: (message) => this.messages.push(message) };
      }
    },
    registerProcessor: (name, cls) => { assert.equal(name, 'aec-capture-worklet'); Processor = cls; },
    Float32Array, Math,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/aec-capture-worklet.js'), 'utf8'), context);
  return { worklet: new Processor(), context };
}

test('AudioWorklet emits 10 ms PCM blocks and outputs silence', () => {
  const { worklet, context } = loadWorklet(48000);
  const input = new Float32Array(128).fill(0.25);
  const output = new Float32Array(128).fill(1);
  for (let i = 0; i < 4; i++) {
    assert.equal(worklet.process([[input]], [[output]]), true);
    context.currentFrame += input.length;
    assert.ok(output.every((sample) => sample === 0));
  }
  assert.equal(worklet.messages.length, 1);
  assert.equal(worklet.messages[0].samples.length, 480);
  assert.ok(worklet.messages[0].samples.every((sample) => sample === 0.25));
  assert.equal(worklet.messages[0].atMs, 0);
  assert.equal(worklet.messages[0].sequence, 0);
});

test('AudioWorklet follows the actual AudioContext sample rate', () => {
  const { worklet, context } = loadWorklet(44100);
  assert.equal(worklet.frameSamples, 441);
  const input = new Float32Array(128).fill(-0.5);
  const output = new Float32Array(128);
  for (let i = 0; i < 4; i++) { worklet.process([[input]], [[output]]); context.currentFrame += input.length; }
  assert.equal(worklet.messages[0].samples.length, 441);
});
