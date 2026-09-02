import { Disclosure } from "./Disclosure.tsx";

/**
 * Where a new user finds the three things the installer asks for: the camera's IP address and
 * the RTSP user + password (needed only for the visible camera; thermal works without them).
 */
export function CredentialsHelp({ open = false }: { open?: boolean }) {
  return (
    <Disclosure label="Where do I find the camera IP, RTSP user and password?" defaultOpen={open}>
      <ol className="help">
        <li><b>Camera IP.</b> Plug the A70 into the computer (or the same switch) and use <i>Setup → Scan network</i> on this site; it lists the camera's address. If the camera reports 0.0.0.0 after a re-plug, press <i>Force IP</i> there once. The default in our lab is 192.168.7.2.</li>
        <li><b>Camera web interface.</b> Open <code>http://&lt;camera IP&gt;</code> in a browser. Log in as <code>admin</code>. The admin password is printed on the <b>calibration certificate / card</b> that shipped in the camera's box (FLIR calls it the initial password). If it has been lost, FLIR support can reset it from the serial number.</li>
        <li><b>RTSP user.</b> In the web interface go to <i>Settings → Users</i> (user management). The RTSP account is listed there, usually named <code>rtsp</code>; set or read its password on that page. This is the only place it lives: it is not on the card and not the admin password.</li>
        <li><b>Where it goes.</b> The installer asks for the three values and writes them only to <code>backend/.env</code> on the operator machine (never to the recording or to this site). To change them later: <code>cd ~/flir-research-interface/backend &amp;&amp; uv run fri-install --no-service</code>.</li>
        <li><b>Without RTSP credentials</b> everything thermal still works; only the visible-camera video and preview are disabled, and the record panel says so.</li>
      </ol>
    </Disclosure>
  );
}
