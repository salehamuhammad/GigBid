"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { auth } from "@/lib/api";

export default function Home() {
  const r = useRouter();
  useEffect(() => { r.replace(auth.get() ? "/inbox" : "/signin"); }, [r]);
  return <main className="center muted">Loading...</main>;
}
