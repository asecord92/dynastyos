import { ImageResponse } from "next/og";

// iOS home-screen icon — the crown mark on the brand gradient (iOS rounds the corners).
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(150deg, #8b5cf6 0%, #4f46e5 100%)",
        }}
      >
        <svg width="110" height="110" viewBox="0 0 24 24" fill="white">
          <path d="M4 7 L8.5 11 L12 5 L15.5 11 L20 7 L18.5 18 L5.5 18 Z" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
