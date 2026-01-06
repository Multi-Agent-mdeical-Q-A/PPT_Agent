// src/stores/agent/utils.ts
export const now = () => Date.now();
export const makeId = (prefix: string) =>
    `${prefix}_${now()}_${Math.random().toString(16).slice(2)}`;

export function clamp01(x: number) {
    return Math.max(0, Math.min(1, x));
}

export function revokeIfBlob(url: string | null) {
    if (url && url.startsWith("blob:")) {
        try {
            URL.revokeObjectURL(url);
        } catch { }
    }
}

export function base64ToU8(b64: string) {
    const bin = atob(b64);
    return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
