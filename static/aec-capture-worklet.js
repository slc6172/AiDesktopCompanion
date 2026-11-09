// Runs on the Web Audio rendering thread. Emits mono 10 ms float PCM at the actual context rate and outputs
// silence so microphone audio is never played back through the speakers.
class AecCaptureWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frameSamples = Math.max(1, Math.round(sampleRate / 100)); // 10 ms at the AudioContext rate
    this.pending = new Float32Array(this.frameSamples);
    this.pendingCount = 0;
    this.sequence = 0;
  }

  process(inputs, outputs) {
    const input = inputs[0] && inputs[0][0];
    const output = outputs[0] && outputs[0][0];
    if (output) output.fill(0);
    if (input) {
      let offset = 0;
      while (offset < input.length) {
        const count = Math.min(this.frameSamples - this.pendingCount, input.length - offset);
        this.pending.set(input.subarray(offset, offset + count), this.pendingCount);
        this.pendingCount += count;
        offset += count;
        if (this.pendingCount === this.frameSamples) {
          const block = this.pending;
          const frameStartMs = ((currentFrame + offset - this.frameSamples) / sampleRate) * 1000;
          this.port.postMessage({ samples: block, sequence: this.sequence++, atMs: frameStartMs }, [block.buffer]);
          this.pending = new Float32Array(this.frameSamples);
          this.pendingCount = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("aec-capture-worklet", AecCaptureWorklet);
