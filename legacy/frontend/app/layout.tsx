import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Roofer | Poland asbestos registry explorer",
  description: "Evidence-led exploration of GeoAzbest registry records, OSM buildings, and official imagery."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><Providers>{children}</Providers></body></html>;
}
