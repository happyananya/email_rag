/** Static export: the build in ./out is uploaded to S3 and served by CloudFront. */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
