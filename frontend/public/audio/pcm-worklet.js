// AudioWorklet processor for ARIA browser mic capture (A.2b-1).
// Runs on the audio render thread and forwards the mono input channel (native
// sample rate, Float32) to the main thread, which downsamples to 16 kHz Int16
// PCM and streams it over /ws/audio. Loaded same-origin from /audio/pcm-worklet.js
// (CSP-safe: no inline script, no eval).
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    const channel = input && input[0];
    if (channel && channel.length) {
      // The render buffer is reused each quantum, so copy before transferring.
      const copy = new Float32Array(channel.length);
      copy.set(channel);
      this.port.postMessage(copy, [copy.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
