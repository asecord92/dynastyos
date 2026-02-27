import "./globals.css";

export const metadata = {
  title: "DynastyOS",
  description: "Fantrax contract dynasty baseball toolkit",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}