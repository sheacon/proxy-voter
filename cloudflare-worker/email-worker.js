export default {
  async email(message, env, ctx) {
    const rawEmail = new Response(message.raw);
    const emailBytes = await rawEmail.arrayBuffer();

    // Keep the connection open so the Fly.io machine stays alive
    // during processing. ctx.waitUntil ensures the worker waits
    // for the full response even if it takes several minutes.
    ctx.waitUntil(
      fetch(env.WEBHOOK_URL, {
        method: "POST",
        headers: {
          "Content-Type": "message/rfc822",
          "X-Webhook-Secret": env.WEBHOOK_SECRET,
          "X-Original-From": message.from,
          "X-Original-To": message.to,
        },
        body: emailBytes,
        signal: AbortSignal.timeout(600000), // 10 minute timeout
      }).catch((err) => {
        console.error("Webhook fetch failed:", err);
      })
    );
  },
};
