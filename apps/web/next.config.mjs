
const address = process.env.API_URL || "http://localhost:8000";
const apiUrl = /^https?:\/\//.test(address) ? address : `http://${address}`;

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
