import { ImageResponse } from "next/og";

// Browser/tab favicon — the crown mark on the brand gradient (matches the login mark).
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
          background: "linear-gradient(150deg, #8b5cf6 0%, #4f46e5 100%)",
          borderRadius: 7,
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="white">
          <path d="M4 7 L8.5 11 L12 5 L15.5 11 L20 7 L18.5 18 L5.5 18 Z" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
