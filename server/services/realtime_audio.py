"""Stateful conversion between Booky's call audio and Gemini Live PCM audio."""
import audioop
import base64
import binascii
import sys


class RealtimeAudioConverter:
    """Keep resampling state per call and per direction across audio chunks."""

    def __init__(self, channel: str):
        """Accept Twilio 8 kHz mu-law or browser 24 kHz little-endian PCM16."""
        if channel not in ('twilio', 'browser'):
            raise ValueError('Unsupported voice channel.')
        self.channel = channel
        self._input_state = None
        self._output_state = None
        self._output_rate = None

    @staticmethod
    def _native_pcm(pcm: bytes) -> bytes:
        """Convert wire PCM16 to the native byte order expected by audioop."""
        return audioop.byteswap(pcm, 2) if sys.byteorder == 'big' else pcm

    def decode_input(self, encoded_audio: str) -> bytes:
        """Decode a client chunk and return mono 16 kHz little-endian PCM16."""
        try:
            audio = base64.b64decode(encoded_audio, validate=True)
        except (ValueError, TypeError, binascii.Error):
            raise ValueError('Invalid call audio payload.') from None
        if not audio:
            return b''
        if self.channel == 'twilio':
            pcm = audioop.ulaw2lin(audio, 2)
            input_rate = 8000
        else:
            if len(audio) % 2:
                raise ValueError('PCM16 audio must contain complete samples.')
            pcm = self._native_pcm(audio)
            input_rate = 24000
        pcm, self._input_state = audioop.ratecv(
            pcm, 2, 1, input_rate, 16000, self._input_state
        )
        return self._native_pcm(pcm)

    def encode_output(self, pcm: bytes, sample_rate: int = 24000) -> str:
        """Convert Gemini PCM16 to the selected client's base64 audio format."""
        if len(pcm) % 2:
            raise ValueError('Gemini returned incomplete PCM16 samples.')
        if self._output_rate != sample_rate:
            self._output_state = None
            self._output_rate = sample_rate
        native_pcm = self._native_pcm(pcm)
        output_rate = 8000 if self.channel == 'twilio' else 24000
        if sample_rate != output_rate:
            native_pcm, self._output_state = audioop.ratecv(
                native_pcm, 2, 1, sample_rate, output_rate, self._output_state, 1, 1
            )
        if self.channel == 'twilio':
            audio = audioop.lin2ulaw(native_pcm, 2)
        else:
            audio = self._native_pcm(native_pcm)
        return base64.b64encode(audio).decode('ascii')

    def reset_output(self):
        """Discard playback resampling history after an interruption or turn end."""
        self._output_state = None
        self._output_rate = None
