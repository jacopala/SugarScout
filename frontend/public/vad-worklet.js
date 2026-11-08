// AudioWorklet: forwards ~21 ms mono frames from the microphone to the main thread,
// where the Segmenter decides when a spoken phrase starts and ends.
class ScoutCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buf = new Float32Array(1024)
    this.n = 0
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i]
        if (this.n === this.buf.length) {
          this.port.postMessage(this.buf.slice(0))
          this.n = 0
        }
      }
    }
    return true
  }
}

registerProcessor('scout-capture', ScoutCapture)
