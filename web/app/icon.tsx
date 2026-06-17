import { ImageResponse } from "next/og";

// Browser/tab favicon — same baseball mark as the iOS icon.
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#1c2030",
          fontSize: 24,
        }}
      >
        ⚾
      </div>
    ),
    { ...size, emoji: "twemoji" }
  );
}
