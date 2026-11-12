import { useRef } from "react";
import type { UserInfo } from "../lib/api.ts";
import { initials, squareCrop } from "../lib/users.ts";

/** A person's round picture, or their initials when they have none. */
export function Avatar({ user, size, className }: { user: Pick<UserInfo, "name" | "avatar"> | null; size: number; className?: string }) {
  const style = { width: size, height: size, fontSize: Math.round(size * 0.4) };
  const cls = `avatar${className ? ` ${className}` : ""}`;
  if (user?.avatar) return <img className={cls} style={style} src={user.avatar} alt="" draggable={false} />;
  return <span className={cls} style={style} aria-hidden>{user ? initials(user.name) : "?"}</span>;
}

const AVATAR_PX = 160;

/** Any photo the browser can decode, cropped to its centre square and shrunk to a ~10 kB JPEG
 *  data URL. Large photos are compressed here, never rejected. */
export async function shrinkPhoto(file: File): Promise<string> {
  const bmp = await createImageBitmap(file);
  try {
    const c = squareCrop(bmp.width, bmp.height, AVATAR_PX);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = c.out;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("this browser can't resize images");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bmp, c.sx, c.sy, c.side, c.side, 0, 0, c.out, c.out);
    let q = 0.85;
    let url = canvas.toDataURL("image/jpeg", q);
    while (url.length > 120_000 && q > 0.4) { q -= 0.15; url = canvas.toDataURL("image/jpeg", q); }
    return url;
  } finally {
    bmp.close();
  }
}

/** A hidden file picker; ``open(id)`` asks for a photo and hands back the shrunk data URL with
 *  the id it was opened for (kept in a ref, so it never depends on a re-render). */
export function usePhotoPicker(onPhoto: (dataUrl: string, id: string) => void, onError: (msg: string) => void) {
  const input = useRef<HTMLInputElement>(null);
  const target = useRef<string | null>(null);
  const el = (
    <input ref={input} type="file" accept="image/*" hidden
      onChange={(e) => {
        const f = e.target.files?.[0];
        const id = target.current;
        e.target.value = "";
        if (!f || !id) return;
        shrinkPhoto(f).then((url) => onPhoto(url, id)).catch((err) => onError(`couldn't read that picture: ${String(err)}`));
      }} />
  );
  return { el, open: (id: string) => { target.current = id; input.current?.click(); } };
}
