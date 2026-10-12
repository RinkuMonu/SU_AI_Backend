require("dotenv").config();
const nodemailer = require("nodemailer");

async function sendTestEmail() {
    const host = process.env.SMTP_HOST || "smtp.gmail.com";
    const port = parseInt(process.env.SMTP_PORT || "587", 10);
    const user = process.env.SMTP_USER || process.env.SMTP_USERNAME;
    const pass = (process.env.SMTP_PASS || process.env.SMTP_PASSWORD || "").replace(/\s/g, "");
    const from = process.env.SMTP_FROM || user;
    const to = "jewelleryappdata@gmail.com";

    console.log("Configuring SMTP Transporter with:", {
        host,
        port,
        user: user ? `${user.slice(0, 4)}***` : undefined,
        to,
    });

    const transporter = nodemailer.createTransport({
        host,
        port,
        secure: port === 465,
        requireTLS: port === 587,
        auth: {
            user,
            pass,
        },
    });

    try {
        console.log("Verifying transporter...");
        await transporter.verify();
        console.log("Transporter verified successfully. Sending email...");

        const info = await transporter.sendMail({
            from: `"SevenUnique AI" <${user}>`,
            to: to,
            subject: "Test Email from SevenUnique AI Backend SMTP",
            text: "Hello! This is a test email sent via SMTP using your configured credentials. Everything is working correctly!",
            html: `
                <div style="font-family: Arial, sans-serif; padding: 20px; color: #333; line-height: 1.6;">
                    <h2 style="color: #4CAF50;">✅ SMTP Email Test Successful!</h2>
                    <p>Hello,</p>
                    <p>This is a test email sent via Gmail SMTP for <strong>SevenUnique AI Backend</strong>.</p>
                    <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;" />
                    <p><strong>Sender:</strong> ${user}</p>
                    <p><strong>Recipient:</strong> ${to}</p>
                    <p><strong>Timestamp:</strong> ${new Date().toISOString()}</p>
                    <p style="color: #777; font-size: 12px; margin-top: 20px;">If you received this email, your SMTP configuration is 100% working!</p>
                </div>
            `,
        });

        console.log("✅ Email sent successfully!");
        console.log("Message ID:", info.messageId);
        console.log("Response:", info.response);
    } catch (error) {
        console.error("❌ Failed to send email:", error.message);
        if (error.code) console.error("Error Code:", error.code);
        if (error.response) console.error("Server Response:", error.response);
    }
}

sendTestEmail();