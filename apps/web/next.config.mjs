
const apiUrl = process.env.API_URL || "http://localhost:8000";

/** Proxy browser API requests to the FastAPI service. */
export default {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};
