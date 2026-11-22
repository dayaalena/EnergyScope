"""Проверки ключевых рисков: время, утечка, повторный запуск и отказ сети."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from modules import ingestion, models, processing
from modules.storage import write_hourly

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT/'config.json').read_text())


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.quality = processing.prepare(ingestion.read_energy(ROOT), ingestion.read_weather(ROOT))

    def test_incomplete_hour_is_missing_not_zero(self):
        e = pd.DataFrame([
            {'startTime':'2024-03-31T00:00Z','publishTime':'2024-03-31T00:30Z','initialDemandOutturn':100},
            {'startTime':'2024-03-31T00:30Z','publishTime':'2024-03-31T01:00Z','initialDemandOutturn':200},
            {'startTime':'2024-03-31T01:00Z','publishTime':'2024-03-31T01:30Z','initialDemandOutturn':300}])
        w = pd.DataFrame({'time':['2024-03-31T00:00Z'],'temperature':[10], 'humidity':[80], 'precipitation':[0], 'wind':[2]})
        f,_ = processing.prepare(e,w)
        self.assertEqual(f.y.iloc[0],150)
        self.assertTrue(pd.isna(f.y.iloc[1]))
        self.assertEqual((f.index[1]-f.index[0]).total_seconds(),3600)

    def test_hourly_grid_survives_clock_change(self):
        for day in ['2024-03-31','2024-10-27']:
            hours=self.frame.loc[day].index
            self.assertEqual(len(hours),24)
            self.assertTrue(hours.is_unique)
            self.assertTrue((hours.to_series().diff().dropna()==pd.Timedelta(hours=1)).all())

    def test_sqlite_second_write_does_not_change_rows(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'data').mkdir()
            f=self.frame.iloc[:48]
            self.assertEqual(write_hourly(d,f),48)
            self.assertEqual(write_hourly(d,f),0)
            with sqlite3.connect(Path(d)/'data/energy.sqlite') as db:
                self.assertEqual(db.execute('select count(*) from hourly').fetchone()[0],48)

    def test_no_network_request_for_completed_cache(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for source,folder,suffix in [('elexon','elexon','json'),('open_meteo','open_meteo','csv')]:
                q=p/'data/raw'/folder;q.mkdir(parents=True)
                (q/f'{source}_2024-01-01_2024-01-03.{suffix}').write_text('cached')
            config={**CONFIG,'start_date':'2024-01-01','end_date':'2024-01-03'}
            with patch('modules.ingestion.fetch') as mocked:
                ingestion.acquire(p,config)
                mocked.assert_not_called()

    def test_network_failure_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'data').mkdir();target=p/'kept.json';target.write_text('kept')
            with patch('urllib.request.urlopen',side_effect=TimeoutError('offline')) as request, patch('time.sleep'):
                with self.assertRaises(RuntimeError):
                    ingestion.fetch(p,'elexon','https://example.invalid',target,CONFIG)
                self.assertEqual(request.call_count,3)
            self.assertEqual(target.read_text(),'kept')

    def test_future_target_and_weather_do_not_change_predictions(self):
        origin=pd.Timestamp('2026-10-20T02:00Z')
        _,x,p,_=models.fit_at(self.frame,CONFIG,origin)
        changed=self.frame.copy()
        changed.loc[changed.index>=origin,'y']*=10
        changed.loc[changed.index>=origin,['temperature','humidity']]=99
        _,x2,p2,_=models.fit_at(changed,CONFIG,origin)
        pd.testing.assert_frame_equal(x,x2)
        for name in p:np.testing.assert_allclose(p[name],p2[name])

    def test_weather_publication_buffer(self):
        with self.assertRaises(ValueError):
            processing.build_features(self.frame,{**CONFIG,'weather_lag_hours':24})

    def test_test_labels_do_not_select_model_or_interval(self):
        cfg={**CONFIG,'validation_folds':1,'calibration_folds':1,'test_folds':1}
        best,w,p,_,_=models.compare(self.frame,cfg)
        altered=self.frame.copy()
        test=p[p.phase=='test']
        altered.loc[pd.to_datetime(test.time.unique(),utc=True),'y']*=2
        best2,w2,p2,_,_=models.compare(altered,cfg)
        self.assertEqual(best,best2)
        self.assertEqual(w,w2)
        self.assertLess(pd.Timestamp(p[p.phase=='validation'].time.max()),pd.Timestamp(p[p.phase=='calibration'].time.min()))
        self.assertLess(pd.Timestamp(p[p.phase=='calibration'].time.max()),pd.Timestamp(p[p.phase=='test'].time.min()))


if __name__=='__main__':unittest.main()
