/** Task 17: the one client-side preference (alert sound, OFF by default) and the tone itself. Both fail quietly. */
const SOUND_KEY = "twingrid.alerts.sound";

export function readSoundPref(storage: Pick<Storage, "getItem"> | null = safeStorage()): boolean {
  try {
    return storage?.getItem(SOUND_KEY) === "on";
  } catch {
    return false;
  }
}

export function writeSoundPref(on: boolean, storage: Pick<Storage, "setItem" | "removeItem"> | null = safeStorage()): void {
  try {
    if (on) storage?.setItem(SOUND_KEY, "on");
    else storage?.removeItem(SOUND_KEY);
  } catch {
    /* a blocked store only means the choice is not remembered */
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** One short two-tone beep (no audio file). Browsers refuse it until the page has had a click or key press; then it is silent. */
export function playAlertTone(): void {
  try {
    const w = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
    const Ctx = w.AudioContext ?? w.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const gain = ctx.createGain();
    gain.gain.value = 0.04;
    gain.connect(ctx.destination);
    [880, 660].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      osc.frequency.value = freq;
      osc.connect(gain);
      osc.start(ctx.currentTime + i * 0.18);
      osc.stop(ctx.currentTime + i * 0.18 + 0.14);
    });
    window.setTimeout(() => void ctx.close().catch(() => undefined), 700);
  } catch {
    /* no audio available */
  }
}
