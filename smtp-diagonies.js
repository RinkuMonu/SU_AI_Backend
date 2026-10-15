const dns = require("node:dns");
const dnsPromises = require("node:dns/promises");

async function diagnoseSmtp() {
    const host = "smtp.gmail.com";

    console.log("Node version:", process.version);
    console.log("DNS servers:", dns.getServers());

    try {
        console.log("DNS lookup:", await dnsPromises.lookup(host));
    } catch (error) {
        console.error("DNS LOOKUP FAILED:", {
            code: error.code,
            message: error.message,
            syscall: error.syscall,
            hostname: error.hostname,
        });
    }

    try {
        console.log("IPv4:", await dnsPromises.resolve4(host));
    } catch (error) {
        console.error("IPv4 resolution failed:", error.code, error.message);
    }

    try {
        console.log("IPv6:", await dnsPromises.resolve6(host));
    } catch (error) {
        console.error("IPv6 resolution failed:", error.code, error.message);
    }
}

diagnoseSmtp();