let audioCtx: AudioContext | null = null;

function getAudioContext() {
  if (!audioCtx) audioCtx = new AudioContext();
  return audioCtx;
}

export function playGoalSound() {
  try {
    const ctx = getAudioContext();
    if (ctx.state === 'suspended') void ctx.resume();
    const start = ctx.currentTime;
    const notes = [523.25, 659.25, 783.99, 1046.5];

    notes.forEach((frequency, index) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const when = start + index * 0.11;

      osc.type = 'triangle';
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0, when);
      gain.gain.linearRampToValueAtTime(0.28, when + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, when + 0.42);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(when);
      osc.stop(when + 0.45);
    });
  } catch {
    // Audio may be unavailable in some browsers.
  }
}
