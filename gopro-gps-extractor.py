import argparse
import exiftool
from ffmpeg import FFmpeg
import json
import logging
import sys
import tempfile

logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(
                    prog='gopro-exif-exporter',
                    description='Extract the GPS data from a video and write it to an image file',
                    add_help=True
                    )
parser.add_argument('-v', '--video-file', help="The source video to extract the GPS data from.", required=True)
parser.add_argument('-i', '--image-file', help="The target image to apply the GPS data to.  If omitted then a single frame will be extracted from the video.")
parser.add_argument('-t', '--timestamp', help="The timestamp (%H:%M:%S) from which to extract the GPS data from the source video", type=str, required=True)
parser.add_argument('-e', '--extract', help="Extract a 1 second clip from the video for processing", type=bool, default=False)
parser.add_argument('-l', '--loglevel', help="The logging level", choices=['DEBUG', 'INFO'], default='INFO')

class Video:
    def __init__(self, video_file, timestamp):
        self.video_file = video_file
        self.timestamp = timestamp

        t = timestamp.split(':')
        hours = int(t[0]) * 60 * 60
        minutes = int(t[1]) * 60
        seconds = int(t[2])

        self.timestamp_seconds = hours + minutes + seconds
    
    def extract_video(self):
        # Seek to timestamp in the video and then extract 1 second. 
        # This is so that we can retrieve the metadata from a smaller
        # video thereby taking less time to process

        logger.info(f"Extracting 1 second of video from {self.video_file} starting at {self.timestamp}")

        # Create tempfile for storage
        self.temp_video_file = tempfile.NamedTemporaryFile()
        self.temp_video_file_name = f'{self.temp_video_file.name}.mp4'

        ffmpeg = (
        FFmpeg()
            .option(
                "y",
            )
            .input(
                self.video_file,
                ss=self.timestamp_seconds,
                t="1",
            )
            .output(
                self.temp_video_file_name,
                c="copy"
            )
        )
        logger.debug(f"ffmpeg arguments: {ffmpeg.arguments}")
        ffmpeg.execute()
        
    def extract_image(self, video):
        # Extract a still from a video file.

        logger.info(f"Extracting image from video {video} at timestamp {self.timestamp}")

        self.image_output_name = f"{(self.video_file.split('.'))[0]}.{self.timestamp_seconds}.jpg"

        ffmpeg = (
            FFmpeg()
            .option("y")
            .input(
                video,
                ss=self.timestamp_seconds,
            )
            .output(
                f"{self.image_output_name}",
                vframes="1",
                **{"qscale": "3"}
            )
        )
        logger.debug(f"ffmpeg arguments: {ffmpeg.arguments}")

        ffmpeg.execute()

        logger.info(f'Image created as {self.image_output_name}')
    
    def update_file(self, file_name: str, data: dict):
        # Update the extracted image with the GPS data from the metadata stream

        logger.info(f"Found match.  Updating image file {file_name} with GPS data")
        with exiftool.ExifTool(common_args=[]) as et:
            for i in data:
                et.execute('-P',
                        i,
                        file_name)

def main():
    # Extract args
    args = parser.parse_args()

    if args.loglevel == 'DEBUG':
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    found_entry = False

    # Initialize object
    obj = Video(args.video_file, args.timestamp)

    if args.extract:
        # Create a smaller copy of the video input
        obj.extract_video()
        video = obj.temp_video_file_name
    else:
        video = args.video_file

    if args.image_file:
        # Image file was provided as an argument.  We don't need to extract the image from the video
        f = args.image_file
    else:
        # Image file was not provided as an argument.  Extract the image.
        obj.extract_image(video)
        f = obj.image_output_name

    # Extract the metadata from the video
    logger.info(f"Extracting metadata from video file {video}")

    with exiftool.ExifTool(common_args=[]) as et:
        metadata = et.execute('-j', '-ee', '-n', '-g3', '-gpslatitude', '-gpslongitude', '-GPSAltitude', '-TimeStamp', '-DeviceName', video)
    
    documents = json.loads(metadata)
    
    logger.info(f"Searching the metadata for timestamp {obj.timestamp_seconds} ({obj.timestamp_seconds})")
    for value in documents[0].values():
        try:
            if isinstance(value, str):
                # Skip strings, we're only looking for dictionaries
                logger.debug("This element is a string.  Skipping")
                continue

            t = int(value.get('TimeStamp'))
            logger.debug(f"Found timestamp {t}")
            if args.extract or t == obj.timestamp_seconds:
                found_entry = True
                data = [
                    f'-GPSLatitude*={value.get("GPSLatitude")}',
                    f'-GPSLongitude*={value.get("GPSLongitude")}',
                    f'-GPSAltitude*={value.get("GPSAltitude")}',
                    f'-model*={value.get("DeviceName")}',
                    '-make*=GoPro',
                    ]
                break
        except AttributeError as e:
            logger.error(str(e))
        except TypeError:
            pass
    
    # Update the image if metadata has been found
    if found_entry:
        obj.update_file(f, data)
    else:
        logger.info(f"No metadata found in {video}")
    
    if args.extract:
        logger.info(f"Deleting temporary video file {video}")
        obj.temp_video_file.close()
    

if __name__ == "__main__":
    main()