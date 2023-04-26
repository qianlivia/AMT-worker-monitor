from argparse import ArgumentParser
import time
from boto3 import client
from collections import Counter
import warnings
from utils import setup_logger
from constants import HIT_ID, ASSIGNMENTS, WORKER_ID, NEXT_TOKEN, \
    QUALIFICATIONS, HITs

logger = setup_logger()


class MTWorkerMonitor(object):
    """Tracks an Amazon Mechanical Turk list of HITs to avoid workers exceeding
    a fixed number of submissions. Provides a submission diversity guarantee.

    To use the monitor, please first create a qualification that will be used to
    blacklist workers if they exceed a certain amount of completed hits.
    If the monitor detects that a worker has exceeded the threshold, it will add
    him the qualification that will prevent him further access to the HITs.
    """

    def __init__(self, max_hits,
                 aws_access_key_id, aws_secret_access_key,
                 mturk_endpoint_url, blacklist_qualification_id,
                 region='us-east-1', sleep_time=10):
        """
        Args:
            max_hits (int): the maximum number of HITS a worker can submit
                before being added to the blacklist (assigned the qualification).
            aws_access_key_id (str): self-explanatory.
            aws_secret_access_key (str): self-explanatory.
            mturk_endpoint_url (str): e.g.,
                https://mturk-requester.us-east-1.amazonaws.com/ or
                https://mturk-requester-sandbox.us-east-1.amazonaws.com
            blacklist_qualification_id (str): the id of a qualification that
                will be assigned to a worker who exceeds 'max_hits'.
            region (str): region of the MT account, e.g., us-east-1.
            sleep_time (int): sleep time between requests to the service to
                check the status of the HITs.
        """
        super(MTWorkerMonitor, self).__init__()
        self.max_hits = max_hits
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.mturk_endpoint_url = mturk_endpoint_url
        self.blacklist_qualification_id = blacklist_qualification_id
        self.sleep_time = sleep_time
        self.mt = client("mturk", aws_access_key_id=self.aws_access_key_id,
                         aws_secret_access_key=self.aws_secret_access_key,
                         region_name=region, endpoint_url=self.mturk_endpoint_url)

    def run(self):
        """Runs an infinite loop (until manually terminated) of fetching and
        checking HITs with a sleep interval.
        """
        init_blacklisted_workers = self.fetch_workers_with_qualification()
        if len(init_blacklisted_workers) > 0:
            logger.info("The initial blacklist has the following workers:")
            for worker_id in init_blacklisted_workers:
                logger.info(f"--- '{worker_id}' ---")
        # run an infinite loop to disqualify workers who exceed a threshold
        logger.info(f"Starting to monitor workers with {self.sleep_time} (s) sleep intervals.")
        while True:
            blacklisted_workers = set(self.fetch_workers_with_qualification())
            hits = self.fetch_and_filter_hits()
            if len(hits) == 0:
                warnings.warn(f"No HITs were found.")

            worker_counter = Counter()
            for hit in hits:
                hit_id = hit[HIT_ID]
                resp = self.mt.list_assignments_for_hit(HITId=hit_id)
                assignments = resp[ASSIGNMENTS]
                for assignment in assignments:
                    worker_id = assignment[WORKER_ID]
                    worker_counter[worker_id] += 1
                    if worker_counter[worker_id] >= self.max_hits \
                            and worker_id not in blacklisted_workers:
                        # adding a worker to the blacklist and assigning a
                        # qualification preventing further submissions
                        blacklisted_workers.add(worker_id)
                        self.mt.associate_qualification_with_worker(
                            WorkerId=worker_id,
                            QualificationTypeId=self.blacklist_qualification_id,
                            SendNotification=False)
                        logger.info(f"worker '{worker_id}' is blacklisted.")
            time.sleep(self.sleep_time)

    def read_hit_ids(self):
        file = open('amt/results/2/ids.txt', 'r')
        ids = [line.strip() for line in file.read().split("\n") if line.strip() != ""]
        file.close()
        return ids

    def fetch_and_filter_hits(self):
        """Fetches all hits and filters the ones that are in ids.txt (or similar files).
        """
        kwargs = {}
        coll = []
        while True:
            resp = self.mt.list_hits(**kwargs)
            if NEXT_TOKEN not in resp:
                break
            kwargs['NextToken'] = resp[NEXT_TOKEN]
            hits = resp[HITs]
            
            coll += [hit for hit in hits if hit[HIT_ID] in self.read_hit_ids()]
        return coll

    def fetch_workers_with_qualification(self):
        """Fetches worker ids that have a granted qualification."""
        kwargs = {'Status': 'Granted',
                  'QualificationTypeId': self.blacklist_qualification_id}
        worker_ids = []
        while True:
            resp = self.mt.list_workers_with_qualification_type(**kwargs)
            if NEXT_TOKEN not in resp:
                break
            kwargs['NextToken'] = resp[NEXT_TOKEN]
            workers = resp[QUALIFICATIONS]
            worker_ids += [w[WORKER_ID] for w in workers]
        return worker_ids


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--max_hits', type=int, required=True,
                        help='the maximum number of HITS a worker can submit '
                             'before being added to the blacklist (assigned '
                             'the qualification).')
    parser.add_argument('--aws_access_key_id', type=str, required=True)
    parser.add_argument('--aws_secret_access_key', type=str, required=True)
    parser.add_argument('--region', type=str, default='us-east-1')
    parser.add_argument('--mturk_endpoint_url', type=str, required=True,
                        help='e.g., https://mturk-requester.us-east-1.amazonaws.com/'
                             ' or https://mturk-requester-sandbox.us-east-1.amazonaws.com')
    parser.add_argument('--sleep_time', type=int, default=10,
                        help='sleep time between requests to the service to '
                             'check the status of the HITs.')
    parser.add_argument('--blacklist_qualification_id', type=str, required=True,
                        help='the id of a qualification that will be assigned to'
                             ' a worker who exceeds \'max_hits\'.')
    args = parser.parse_args()
    monitor = MTWorkerMonitor(**vars(args))
    monitor.run()
